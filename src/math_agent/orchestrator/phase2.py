"""Phase 2 loop: Lean 4 formalization."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from math_agent.agents.cli_agent import CLIAgent
from math_agent.documents.module_memo import ModuleMemo
from math_agent.lean.compiler import LeanCompiler, CompileResult
from math_agent.lean.project import LeanProject
from math_agent.lean.module_splitter import ModuleSplitter
from math_agent.lean.external_claims import ExternalClaimRegistry
from math_agent.lean.mathlib_search import (
    search_mathlib,
    format_search_results,
)

logger = logging.getLogger(__name__)


@dataclass
class Phase2Event:
    event_type: str  # skeleton_created | module_started | compile_result | sorry_eliminated | external_claim_added | module_done | structural_issue
    module_name: str = ""
    content: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class Phase2Result:
    success: bool
    modules_completed: list[str] = field(default_factory=list)
    modules_failed: list[str] = field(default_factory=list)
    external_claims: list[dict] = field(default_factory=list)
    structural_issue: str | None = None  # if set, Phase 1 needs to re-generate
    events: list[Phase2Event] = field(default_factory=list)


class Phase2Runner:
    """Phase 2: Lean 4 Formalization.

    Takes a complete mathematical proof from Phase 1 and formalizes it
    in Lean 4 with sorry-elimination and external claim management.
    """

    def __init__(
        self,
        cli_agent: CLIAgent,
        lean_project: LeanProject,
        compiler: LeanCompiler,
        runs_dir: Path,
        proof: str,
    ):
        self.cli = cli_agent
        self.project = lean_project
        self.compiler = compiler
        self.runs_dir = runs_dir
        self.proof = proof
        self.claims = ExternalClaimRegistry()
        self.splitter = ModuleSplitter()
        self._events: list[Phase2Event] = []

    def _emit(self, event: Phase2Event) -> None:
        self._events.append(event)
        logger.info(
            "Phase2 [%s] %s: %s",
            event.event_type,
            event.module_name,
            event.content[:120],
        )

    async def run(self) -> Phase2Result:
        """Run Phase 2 to completion."""
        # Initialize Lean project
        self.project.init()

        # Split proof into modules
        module_plans = self.splitter.split(self.proof)
        module_names = [m.name for m in module_plans]

        # Generate skeleton code
        skeletons = await self.cli.generate_skeleton(self.proof, module_names)

        for name, code in skeletons.items():
            self.project.add_module(name, code)

        self._emit(
            Phase2Event(
                "skeleton_created",
                content=f"Created {len(skeletons)} modules: {', '.join(skeletons.keys())}",
            )
        )

        # Process each module
        completed = []
        failed = []
        max_retries_per_module = 10
        max_external_claims = 5

        for plan in module_plans:
            name = plan.name
            mod_memo = ModuleMemo(
                self.runs_dir / f"{name}_MEMO.md", name
            )

            self._emit(
                Phase2Event(
                    "module_started",
                    module_name=name,
                    content=plan.description,
                )
            )

            code = self.project.read_module(name)
            module_done = False
            prev_error_count: int | None = None
            stall_count = 0  # consecutive attempts with no error reduction
            max_stall = 3    # give up fixing after 3 stalled attempts

            for attempt in range(max_retries_per_module):
                # Compile
                module_path = (
                    self.project.workspace / "MathAgent" / f"{name}.lean"
                )
                result = await self.compiler.compile_file(module_path)

                sorry_count = self.compiler.count_sorries(module_path)
                mod_memo.update_sorry_count(sorry_count)

                self._emit(
                    Phase2Event(
                        "compile_result",
                        module_name=name,
                        content=f"Attempt {attempt + 1}: {'OK' if result.success else 'FAIL'}, {sorry_count} sorry(s)",
                        metadata={
                            "success": result.success,
                            "sorry_count": sorry_count,
                            "errors": len(result.errors),
                        },
                    )
                )

                if result.success and sorry_count == 0:
                    module_done = True
                    break

                # Stage 1: Fix compiler errors
                if not result.success:
                    cur_errors = len(result.errors)

                    # Detect stalled fix loop (same or more errors)
                    if prev_error_count is not None and cur_errors >= prev_error_count:
                        stall_count += 1
                    else:
                        stall_count = 0
                    prev_error_count = cur_errors

                    if stall_count >= max_stall:
                        logger.warning(
                            "Module %s: fix loop stalled after %d attempts "
                            "(%d errors persist). Moving to sorry fallback.",
                            name, attempt + 1, cur_errors,
                        )
                        self._emit(
                            Phase2Event(
                                "compile_result",
                                module_name=name,
                                content=(
                                    f"Fix loop stalled ({cur_errors} errors "
                                    f"persist after {stall_count} attempts). "
                                    f"Requesting sorry-based skeleton."
                                ),
                            )
                        )
                        # Ask the LLM to give up on the full proof and produce
                        # a compiling skeleton with sorry instead
                        code = await self.cli.fix_compiler_error(
                            name,
                            code,
                            (
                                "STOP trying to fix individual errors. The current "
                                "approach is not working. Instead, replace ALL broken "
                                "proof steps with `sorry`. Keep only the theorem "
                                "statement and imports. The goal is a COMPILING file, "
                                "even if every proof body is `sorry`.\n\n"
                                "Previous errors:\n"
                                + "\n".join(
                                    f"{e.file}:{e.line}:{e.column}: {e.message}"
                                    for e in result.errors[:5]
                                )
                            ),
                        )
                        self.project.write_module(name, code)
                        stall_count = 0
                        prev_error_count = None
                        continue

                    error_text = "\n".join(
                        f"{e.file}:{e.line}:{e.column}: {e.message}"
                        for e in result.errors
                    )
                    mod_memo.add_compiler_error(error_text)

                    # --- Mathlib API search for unknown identifiers ---
                    mathlib_hints = ""
                    unknown_ids = set()
                    for e in result.errors:
                        # Extract unknown identifiers from error messages
                        for pattern in [
                            r"Unknown (?:identifier|constant) [`'](\S+)[`']",
                            r"unknown identifier [`'](\S+)[`']",
                            r"Invalid field [`'](\S+)[`']",
                            r"does not contain [`'](\S+)[`']",
                        ]:
                            for m in re.finditer(pattern, e.message, re.IGNORECASE):
                                # Use the last part of the dotted name as search term
                                full_name = m.group(1).strip("'`")
                                parts = full_name.rsplit(".", 1)
                                unknown_ids.add(parts[-1])
                                if len(parts) > 1:
                                    unknown_ids.add(parts[0])

                    if unknown_ids:
                        all_hits = []
                        for uid in list(unknown_ids)[:5]:
                            hits = await search_mathlib(
                                self.project.workspace, uid, max_results=5,
                            )
                            all_hits.extend(hits)
                        if all_hits:
                            mathlib_hints = format_search_results(all_hits[:15])
                            logger.info(
                                "Mathlib search for %s → %d hits",
                                unknown_ids, len(all_hits),
                            )

                    code = await self.cli.fix_compiler_error(
                        name, code, error_text,
                        mathlib_hints=mathlib_hints,
                    )
                    self.project.write_module(name, code)
                    continue

                # Stage 2: Eliminate sorry
                if sorry_count > 0:
                    # --- Try exact? first ---
                    lean_suggestions = ""
                    try:
                        suggestions = await self.compiler.suggest_at_sorry(
                            module_path, timeout_secs=90,
                        )
                        if suggestions:
                            # Apply first suggestion directly
                            sug = suggestions[0]
                            sug_text = sug["suggestion"]
                            self._emit(
                                Phase2Event(
                                    "compile_result",
                                    module_name=name,
                                    content=f"exact? found: {sug_text[:100]}",
                                )
                            )
                            lean_suggestions = f"Line {sug['line']}: {sug_text}"

                            # Try applying suggestion directly
                            mod_code = code
                            # Replace first sorry with the suggestion
                            mod_code = re.sub(
                                r"\bsorry\b",
                                sug_text,
                                mod_code,
                                count=1,
                            )
                            self.project.write_module(name, mod_code)
                            # Recompile to check
                            result_sug = await self.compiler.compile_file(module_path)
                            if result_sug.success or len(result_sug.errors) == 0:
                                new_sorry_count = self.compiler.count_sorries(module_path)
                                if new_sorry_count < sorry_count:
                                    code = mod_code
                                    self._emit(
                                        Phase2Event(
                                            "sorry_eliminated",
                                            module_name=name,
                                            content=f"exact? suggestion worked! sorry: {sorry_count} -> {new_sorry_count}",
                                        )
                                    )
                                    continue
                            # Suggestion didn't compile cleanly, revert
                            self.project.write_module(name, code)
                    except Exception as exc:
                        logger.debug("exact? failed: %s", exc)

                    # --- Search Mathlib for clues about the sorry ---
                    mathlib_hints = ""
                    # Extract identifiers near sorry lines for search context
                    sorry_lines = [
                        line for line in code.splitlines()
                        if "sorry" in line and not line.strip().startswith("--")
                    ]
                    if sorry_lines:
                        # Look for identifiers in nearby lines
                        search_terms = set()
                        for sl in sorry_lines[:2]:
                            # Find capitalized words that might be Mathlib names
                            for tok in re.findall(r"\b[A-Z]\w+(?:\.\w+)*", code):
                                if len(tok) > 3 and tok not in {"Type", "Prop", "True", "False", "Sort"}:
                                    search_terms.add(tok.split(".")[-1])
                        all_hits = []
                        for term in list(search_terms)[:3]:
                            hits = await search_mathlib(
                                self.project.workspace, term, max_results=5,
                            )
                            all_hits.extend(hits)
                        if all_hits:
                            mathlib_hints = format_search_results(all_hits[:10])

                    code = await self.cli.eliminate_sorry(
                        name, code, f"{sorry_count} sorry(s) remaining",
                        lean_suggestions=lean_suggestions,
                        mathlib_hints=mathlib_hints,
                    )
                    self.project.write_module(name, code)

                    # Recompile to check
                    result2 = await self.compiler.compile_file(module_path)
                    new_sorry_count = self.compiler.count_sorries(
                        module_path
                    )

                    if new_sorry_count < sorry_count:
                        self._emit(
                            Phase2Event(
                                "sorry_eliminated",
                                module_name=name,
                                content=f"Reduced sorry: {sorry_count} -> {new_sorry_count}",
                            )
                        )
                        continue

                    # Stage 2b: Accept as external claim if stuck
                    if self.claims.count() < max_external_claims:
                        code = await self.cli.accept_external_claim(
                            name,
                            code,
                            f"sorry at attempt {attempt + 1}",
                        )
                        self.project.write_module(name, code)
                        self._emit(
                            Phase2Event(
                                "external_claim_added",
                                module_name=name,
                                content=f"Accepted external claim (total: {self.claims.count() + 1})",
                            )
                        )
                        continue

                    # Stage 3: Too many external claims -> structural issue
                    issue = (
                        f"Module {name} has {sorry_count} unresolvable sorry(s) "
                        f"and {self.claims.count()} external claims already used. "
                        f"Structural issue: proof approach may need revision."
                    )
                    self._emit(
                        Phase2Event(
                            "structural_issue",
                            module_name=name,
                            content=issue,
                        )
                    )
                    return Phase2Result(
                        success=False,
                        modules_completed=completed,
                        modules_failed=[name]
                        + [
                            p.name
                            for p in module_plans
                            if p.name not in completed and p.name != name
                        ],
                        external_claims=[
                            {
                                "name": c.name,
                                "type": c.lean_type,
                                "justification": c.justification,
                            }
                            for c in self.claims.list_claims()
                        ],
                        structural_issue=issue,
                        events=self._events,
                    )

            if module_done:
                completed.append(name)
                self._emit(
                    Phase2Event(
                        "module_done",
                        module_name=name,
                        content="Module complete.",
                    )
                )
            else:
                failed.append(name)

        return Phase2Result(
            success=len(failed) == 0,
            modules_completed=completed,
            modules_failed=failed,
            external_claims=[
                {
                    "name": c.name,
                    "type": c.lean_type,
                    "justification": c.justification,
                }
                for c in self.claims.list_claims()
            ],
            events=self._events,
        )
