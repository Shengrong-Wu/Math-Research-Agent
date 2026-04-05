"""Wraps Lean 4 compiler invocation and error parsing."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path


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


class LeanCompiler:
    """Interface to the Lean 4 compiler via lake."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    async def compile_file(self, file_path: Path) -> CompileResult:
        """Compile a single .lean file using ``lake env lean``."""
        proc = await asyncio.create_subprocess_exec(
            "lake",
            "env",
            "lean",
            str(file_path),
            cwd=str(self.workspace),
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
        proc = await asyncio.create_subprocess_exec(
            "lake",
            "build",
            cwd=str(self.workspace),
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
