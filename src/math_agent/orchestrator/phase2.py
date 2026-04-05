"""Phase 2 loop: Lean 4 formalization."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from math_agent.agents.cli_agent import CLIAgent
from math_agent.documents.module_memo import ModuleMemo
from math_agent.lean.compiler import LeanCompiler, CompileResult
from math_agent.lean.project import LeanProject
from math_agent.lean.module_splitter import ModuleSplitter
from math_agent.lean.external_claims import ExternalClaimRegistry

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
                    error_text = "\n".join(
                        f"{e.file}:{e.line}:{e.column}: {e.message}"
                        for e in result.errors
                    )
                    mod_memo.add_compiler_error(error_text)
                    code = await self.cli.fix_compiler_error(
                        name, code, error_text
                    )
                    self.project.write_module(name, code)
                    continue

                # Stage 2: Eliminate sorry
                if sorry_count > 0:
                    code = await self.cli.eliminate_sorry(
                        name, code, f"{sorry_count} sorry(s) remaining"
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
