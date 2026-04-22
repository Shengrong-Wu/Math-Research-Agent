"""Lean Toolplane — unified interface for Lean interaction and search.

Wraps the LeanCompiler with higher-level operations:
- Tactic probing (exact?, apply?, rw?)
- Ranked repair suggestions
- Mathlib and project-local search
- Goal state capture
- Availability check

All operations are guarded: if Lean is not installed, the toolplane
reports itself as unavailable and all methods return empty results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from math_agent.lean.compiler import LeanCompiler, CompileResult, CompilerError

logger = logging.getLogger(__name__)


@dataclass
class RepairSuggestion:
    """A ranked suggestion for fixing a sorry."""

    tactic: str        # "exact?" | "apply?" | "rw?"
    suggestion: str    # the actual Lean code
    score: float = 1.0  # higher = more likely to work


class LeanToolplane:
    """Unified Lean interaction interface.

    Wraps a LeanCompiler and provides high-level operations for
    optional Phase 1 verification and Lean search helpers.
    """

    def __init__(
        self,
        compiler: LeanCompiler | None = None,
        workspace: Path | None = None,
    ) -> None:
        self._compiler = compiler
        self._workspace = workspace or (compiler.workspace if compiler else None)

    @staticmethod
    def is_available() -> bool:
        """Check if Lean/elan is installed."""
        try:
            from math_agent.lean.compiler import _find_lake
            _find_lake()
            return True
        except FileNotFoundError:
            return False

    @property
    def compiler(self) -> LeanCompiler | None:
        return self._compiler

    # ------------------------------------------------------------------
    # Compilation
    # ------------------------------------------------------------------

    async def compile_file(self, file_path: Path) -> CompileResult | None:
        """Compile a file. Returns None if toolplane is unavailable."""
        if not self._compiler:
            return None
        return await self._compiler.compile_file(file_path)

    async def get_diagnostics(self, file_path: Path) -> list[CompilerError]:
        """Return all diagnostics for a file."""
        if not self._compiler:
            return []
        return await self._compiler.get_diagnostics(file_path)

    # ------------------------------------------------------------------
    # Tactic probing
    # ------------------------------------------------------------------

    async def exact_at(self, file_path: Path, line: int) -> list[str]:
        """Run exact? at a sorry position."""
        if not self._compiler:
            return []
        return await self._compiler.exact_at(file_path, line)

    async def apply_at(self, file_path: Path, line: int) -> list[str]:
        """Run apply? at a sorry position."""
        if not self._compiler:
            return []
        return await self._compiler.apply_at(file_path, line)

    async def rw_at(self, file_path: Path, line: int) -> list[str]:
        """Run rw? at a sorry position."""
        if not self._compiler:
            return []
        return await self._compiler.rw_at(file_path, line)

    async def ranked_repairs(
        self, file_path: Path, line: int,
    ) -> list[RepairSuggestion]:
        """Combine exact?/apply?/rw? results into a scored list.

        Attempts all three search tactics and returns suggestions
        ranked by tactic reliability (exact? > apply? > rw?).
        """
        if not self._compiler:
            return []

        suggestions: list[RepairSuggestion] = []

        # exact? is most specific — highest score
        for s in await self._compiler.exact_at(file_path, line):
            suggestions.append(RepairSuggestion("exact?", s, score=3.0))

        # apply? is broader
        for s in await self._compiler.apply_at(file_path, line):
            # Deduplicate with exact? results
            if not any(r.suggestion == s for r in suggestions):
                suggestions.append(RepairSuggestion("apply?", s, score=2.0))

        # rw? is the broadest
        for s in await self._compiler.rw_at(file_path, line):
            if not any(r.suggestion == s for r in suggestions):
                suggestions.append(RepairSuggestion("rw?", s, score=1.0))

        suggestions.sort(key=lambda r: r.score, reverse=True)
        return suggestions

    async def get_goal_state(self, file_path: Path, line: int) -> str:
        """Best-effort current goal capture near a sorry line."""
        if not self._compiler:
            return ""
        return await self._compiler.get_goal_state(file_path, line)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_mathlib(
        self, query: str, max_results: int = 20,
    ) -> list:
        """Search installed Mathlib for theorems matching *query*."""
        if not self._workspace:
            return []
        from math_agent.lean.mathlib_search import search_mathlib
        return await search_mathlib(self._workspace, query, max_results)

    async def search_project(
        self, query: str, max_results: int = 10,
    ) -> list:
        """Search project-local declarations for *query*."""
        if not self._workspace:
            return []
        from math_agent.lean.mathlib_search import search_mathlib
        # Search in the project's own module directory
        project_dir = self._workspace / "MathAgent"
        if project_dir.exists():
            return await search_mathlib(
                self._workspace, query, max_results,
            )
        return []

    # ------------------------------------------------------------------
    # Phase 1 helpers
    # ------------------------------------------------------------------

    async def check_statement(
        self, lean_code: str, module_name: str = "StatementCheck",
    ) -> CompileResult | None:
        """Compile a Lean statement (no proof body) to type-check it.

        Writes the code to a temporary module file, compiles it, and
        removes the file afterward.
        """
        if not self._compiler or not self._workspace:
            return None

        module_dir = self._workspace / "MathAgent"
        module_dir.mkdir(parents=True, exist_ok=True)
        tmp_file = module_dir / f"{module_name}_{uuid4().hex}.lean"
        tmp_file.write_text(lean_code, encoding="utf-8")

        try:
            result = await self._compiler.compile_file(tmp_file)
            return result
        finally:
            tmp_file.unlink(missing_ok=True)

    async def check_sketch(
        self, lean_code: str, module_name: str = "SketchCheck",
    ) -> CompileResult | None:
        """Compile a Lean lemma sketch (statement + sorry body).

        Same as check_statement but the code is expected to contain sorry's.
        """
        return await self.check_statement(lean_code, module_name)
