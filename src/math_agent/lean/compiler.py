"""Wraps Lean 4 compiler invocation and error parsing."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CompilerError:
    file: str
    line: int
    column: int
    message: str
    severity: str = "error"  # error | warning


@dataclass
class CompileResult:
    success: bool
    errors: list[CompilerError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""


def _elan_env() -> dict[str, str]:
    """Return a copy of ``os.environ`` with ``~/.elan/bin`` prepended
    to ``PATH`` so that ``lake`` and ``lean`` are always found, even when
    the user's shell profile hasn't sourced ``~/.elan/env``.
    """
    env = os.environ.copy()
    elan_bin = str(Path.home() / ".elan" / "bin")
    current = env.get("PATH", "")
    if elan_bin not in current:
        env["PATH"] = elan_bin + os.pathsep + current
    return env


def _find_lake() -> str:
    """Return the absolute path to ``lake``, preferring ``~/.elan/bin``."""
    elan_lake = Path.home() / ".elan" / "bin" / "lake"
    if elan_lake.exists():
        return str(elan_lake)
    found = shutil.which("lake")
    if found:
        return found
    raise FileNotFoundError(
        "Cannot find `lake`. Install elan: https://github.com/leanprover/elan"
    )


class LeanCompiler:
    """Interface to the Lean 4 compiler via lake."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self._lake = _find_lake()
        self._env = _elan_env()

    async def compile_file(self, file_path: Path) -> CompileResult:
        """Compile a single .lean file using ``lake env lean``.

        *file_path* may be absolute or relative to the current directory;
        it is automatically made relative to the workspace so that
        ``lake env lean`` resolves it correctly.
        """
        # lake env lean expects a path relative to the workspace
        abs_path = file_path.resolve()
        try:
            rel_path = abs_path.relative_to(self.workspace.resolve())
        except ValueError:
            rel_path = abs_path  # fall back to absolute
        proc = await asyncio.create_subprocess_exec(
            self._lake,
            "env",
            "lean",
            str(rel_path),
            cwd=str(self.workspace),
            env=self._env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode()
        stderr = stderr_bytes.decode()

        errors = self.parse_errors(stderr)
        warnings = [
            e.message for e in errors if e.severity == "warning"
        ]
        hard_errors = [e for e in errors if e.severity == "error"]

        return CompileResult(
            success=proc.returncode == 0 and len(hard_errors) == 0,
            errors=hard_errors,
            warnings=warnings,
            stdout=stdout,
            stderr=stderr,
        )

    async def build_project(self) -> CompileResult:
        """Run ``lake build`` on the entire project."""
        logger.info("Running `lake build` in %s", self.workspace)
        proc = await asyncio.create_subprocess_exec(
            self._lake,
            "build",
            cwd=str(self.workspace),
            env=self._env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode()
        stderr = stderr_bytes.decode()

        errors = self.parse_errors(stderr)
        warnings = [
            e.message for e in errors if e.severity == "warning"
        ]
        hard_errors = [e for e in errors if e.severity == "error"]

        return CompileResult(
            success=proc.returncode == 0 and len(hard_errors) == 0,
            errors=hard_errors,
            warnings=warnings,
            stdout=stdout,
            stderr=stderr,
        )

    async def cache_get(self) -> bool:
        """Run ``lake exe cache get`` to download precompiled Mathlib
        oleans.  Returns *True* if the command succeeds.
        """
        logger.info("Downloading Mathlib cache (`lake exe cache get`) …")
        proc = await asyncio.create_subprocess_exec(
            self._lake,
            "exe",
            "cache",
            "get",
            cwd=str(self.workspace),
            env=self._env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        ok = proc.returncode == 0
        if ok:
            logger.info("Mathlib cache downloaded successfully.")
        else:
            logger.warning(
                "Mathlib cache download failed (rc=%d): %s",
                proc.returncode,
                stderr_bytes.decode()[:500],
            )
        return ok

    async def suggest_at_sorry(
        self,
        file_path: Path,
        *,
        timeout_secs: int = 120,
        max_heartbeats: int = 800000,
    ) -> list[dict]:
        """Replace each ``sorry`` with ``exact?`` and capture suggestions.

        For every ``sorry`` in *file_path*, creates a temporary copy with
        that sorry replaced by ``exact?``, compiles it, and extracts any
        ``Try this:`` suggestions from the output.

        Returns a list of dicts::

            [{"line": 12, "suggestion": "exact irrational_sqrt_two",
              "original": "sorry"}, ...]

        Only the *first* sorry is attempted (to keep compile time bounded).
        """
        text = file_path.read_text()
        lines = text.splitlines()

        # Find sorry locations (ignoring comments)
        sorry_locs: list[int] = []
        stripped = re.sub(r"/-.*?-/", "", text, flags=re.DOTALL)
        for i, raw in enumerate(stripped.splitlines()):
            clean = re.sub(r"--.*", "", raw)
            if re.search(r"\bsorry\b", clean):
                sorry_locs.append(i)

        if not sorry_locs:
            return []

        results: list[dict] = []

        # Only try the first sorry to bound compile time
        loc = sorry_locs[0]

        # Build a modified file with sorry -> exact?
        mod_lines = list(lines)
        original_line = mod_lines[loc]
        mod_lines[loc] = re.sub(
            r"\bsorry\b",
            "exact?",
            original_line,
            count=1,
        )

        # Prepend a heartbeat override
        header = f"set_option maxHeartbeats {max_heartbeats}\n"
        mod_text = header + "\n".join(mod_lines) + "\n"

        # Write to a temp file alongside the original
        tmp_path = file_path.with_suffix(".lean.suggest_tmp")
        tmp_path.write_text(mod_text)

        try:
            abs_path = tmp_path.resolve()
            try:
                rel_path = abs_path.relative_to(self.workspace.resolve())
            except ValueError:
                rel_path = abs_path

            proc = await asyncio.create_subprocess_exec(
                self._lake,
                "env",
                "lean",
                str(rel_path),
                cwd=str(self.workspace),
                env=self._env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout_secs,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                logger.info("exact? timed out after %ds", timeout_secs)
                return results

            output = stderr_bytes.decode() + "\n" + stdout_bytes.decode()

            # Look for "Try this: ..." lines
            for line in output.splitlines():
                m = re.search(r"Try this:\s*(.+)", line)
                if m:
                    suggestion = m.group(1).strip()
                    # Clean up [apply] / [exact] prefixes
                    suggestion = re.sub(r"^\[(apply|exact)\]\s*", "", suggestion)
                    results.append(
                        {
                            "line": loc + 1,  # 1-indexed
                            "suggestion": suggestion,
                            "original": "sorry",
                        }
                    )
                    break
        finally:
            tmp_path.unlink(missing_ok=True)

        return results

    async def probe_tactic(
        self,
        file_path: Path,
        line: int,
        tactic: str = "exact?",
        *,
        timeout_secs: int = 120,
        max_heartbeats: int = 800000,
    ) -> list[str]:
        """Replace the ``sorry`` at *line* (1-indexed) with *tactic* and
        capture any ``Try this:`` suggestions.

        This generalizes ``suggest_at_sorry`` to support ``apply?``,
        ``rw?``, and other search tactics.
        """
        text = file_path.read_text()
        lines = text.splitlines()
        if line < 1 or line > len(lines):
            return []

        idx = line - 1
        original = lines[idx]
        if "sorry" not in original:
            return []

        mod_lines = list(lines)
        mod_lines[idx] = re.sub(r"\bsorry\b", tactic, original, count=1)

        header = f"set_option maxHeartbeats {max_heartbeats}\n"
        mod_text = header + "\n".join(mod_lines) + "\n"

        tmp_path = file_path.with_suffix(f".lean.{tactic.replace('?', '_')}_tmp")
        tmp_path.write_text(mod_text)

        suggestions: list[str] = []
        try:
            abs_path = tmp_path.resolve()
            try:
                rel_path = abs_path.relative_to(self.workspace.resolve())
            except ValueError:
                rel_path = abs_path

            proc = await asyncio.create_subprocess_exec(
                self._lake, "env", "lean", str(rel_path),
                cwd=str(self.workspace), env=self._env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout_secs,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return suggestions

            output = stderr_bytes.decode() + "\n" + stdout_bytes.decode()
            for out_line in output.splitlines():
                m = re.search(r"Try this:\s*(.+)", out_line)
                if m:
                    s = m.group(1).strip()
                    s = re.sub(r"^\[(apply|exact|rw)\]\s*", "", s)
                    suggestions.append(s)
        finally:
            tmp_path.unlink(missing_ok=True)

        return suggestions

    async def exact_at(self, file_path: Path, line: int, **kw) -> list[str]:
        """Run ``exact?`` at the sorry on *line*."""
        return await self.probe_tactic(file_path, line, "exact?", **kw)

    async def apply_at(self, file_path: Path, line: int, **kw) -> list[str]:
        """Run ``apply?`` at the sorry on *line*."""
        return await self.probe_tactic(file_path, line, "apply?", **kw)

    async def rw_at(self, file_path: Path, line: int, **kw) -> list[str]:
        """Run ``rw?`` at the sorry on *line*."""
        return await self.probe_tactic(file_path, line, "rw?", **kw)

    async def get_goal_state(
        self,
        file_path: Path,
        line: int,
        *,
        timeout_secs: int = 120,
        max_heartbeats: int = 800000,
    ) -> str:
        """Best-effort capture of the goal state at a ``sorry`` line.

        This uses ``trace_state`` inside a temporary file. It is intentionally
        heuristic and serves as a lightweight fallback until an LSP-backed
        implementation is available.
        """
        text = file_path.read_text()
        lines = text.splitlines()
        if line < 1 or line > len(lines):
            return ""

        idx = line - 1
        original = lines[idx]
        if "sorry" not in original:
            return ""

        if re.search(r"\bby\b.*\bsorry\b", original):
            replacement = re.sub(
                r"\bsorry\b",
                "trace_state; sorry",
                original,
                count=1,
            )
        else:
            replacement = re.sub(
                r"\bsorry\b",
                "(by trace_state; sorry)",
                original,
                count=1,
            )

        mod_lines = list(lines)
        mod_lines[idx] = replacement
        header = (
            f"set_option maxHeartbeats {max_heartbeats}\n"
            "set_option pp.universes true\n"
        )
        mod_text = header + "\n".join(mod_lines) + "\n"

        tmp_path = file_path.with_suffix(".lean.goal_state_tmp")
        tmp_path.write_text(mod_text)

        try:
            abs_path = tmp_path.resolve()
            try:
                rel_path = abs_path.relative_to(self.workspace.resolve())
            except ValueError:
                rel_path = abs_path

            proc = await asyncio.create_subprocess_exec(
                self._lake,
                "env",
                "lean",
                str(rel_path),
                cwd=str(self.workspace),
                env=self._env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout_secs,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return ""

            output = (stderr_bytes.decode() + "\n" + stdout_bytes.decode()).strip()
            goal_lines = [
                out_line.rstrip()
                for out_line in output.splitlines()
                if "⊢" in out_line
                or "goals" in out_line.lower()
                or "case " in out_line
                or "trace" in out_line.lower()
            ]
            return "\n".join(goal_lines).strip() or output
        finally:
            tmp_path.unlink(missing_ok=True)

    async def get_diagnostics(self, file_path: Path) -> list[CompilerError]:
        """Compile *file_path* and return all diagnostics (errors + warnings)."""
        result = await self.compile_file(file_path)
        return self.parse_errors(result.stderr)

    def sorrify_region(
        self, file_path: Path, start_line: int, end_line: int,
    ) -> str:
        """Replace lines *start_line*–*end_line* (1-indexed, inclusive) with
        ``sorry`` and return the modified file content.

        Used by the sorrify-and-recurse policy (P5) to freeze valid code
        while isolating failing regions.
        """
        text = file_path.read_text()
        lines = text.splitlines()
        # Compute indentation from start line
        if start_line < 1:
            start_line = 1
        if end_line > len(lines):
            end_line = len(lines)
        indent = len(lines[start_line - 1]) - len(lines[start_line - 1].lstrip())
        sorry_line = " " * indent + "sorry"
        new_lines = lines[: start_line - 1] + [sorry_line] + lines[end_line:]
        result = "\n".join(new_lines) + "\n"
        file_path.write_text(result)
        return result

    def count_sorries(self, file_path: Path) -> int:
        """Count remaining ``sorry``'s in a .lean file.

        Only counts occurrences that are *not* inside line comments
        (``--``) or block comments (``/- ... -/``).
        """
        text = file_path.read_text()

        # Strip block comments (may be nested, but we do a simple non-greedy pass)
        text = re.sub(r"/-.*?-/", "", text, flags=re.DOTALL)

        count = 0
        for line in text.splitlines():
            # Remove line comments
            line = re.sub(r"--.*", "", line)
            # Match whole-word sorry (not part of another identifier)
            count += len(re.findall(r"\bsorry\b", line))
        return count

    @staticmethod
    def parse_errors(stderr: str) -> list[CompilerError]:
        """Parse Lean compiler error output into structured errors.

        The Lean error format is::

            filename:line:col: severity: message
            possibly continued on the next line(s)

        Severity is typically ``error`` or ``warning``.
        """
        # Pattern: filename:line:col: severity: first line of message
        header_re = re.compile(
            r"^(?P<file>.+?):(?P<line>\d+):(?P<col>\d+):\s*"
            r"(?P<severity>error|warning):\s*(?P<msg>.*)$"
        )

        results: list[CompilerError] = []
        current: CompilerError | None = None

        for raw_line in stderr.splitlines():
            m = header_re.match(raw_line)
            if m:
                # Flush the previous error if any
                if current is not None:
                    current.message = current.message.rstrip()
                    results.append(current)
                current = CompilerError(
                    file=m.group("file"),
                    line=int(m.group("line")),
                    column=int(m.group("col")),
                    message=m.group("msg"),
                    severity=m.group("severity"),
                )
            elif current is not None:
                # Continuation line -- append to current message
                current.message += "\n" + raw_line

        # Don't forget the last accumulated error
        if current is not None:
            current.message = current.message.rstrip()
            results.append(current)

        return results
