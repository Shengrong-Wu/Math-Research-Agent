"""Per-Lean-module MEMO management for Phase 2."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModuleMemoState:
    """State of a per-module MEMO document."""

    module_name: str
    roadmap: str = ""
    sorry_count: int = 0
    external_claims: list[str] = field(default_factory=list)
    compiler_errors: list[str] = field(default_factory=list)
    status: str = ""  # e.g. "in_progress", "complete", "blocked"


class ModuleMemo:
    """Manages a per-Lean-module MEMO file for Phase 2 formalization."""

    def __init__(self, path: Path, module_name: str) -> None:
        self.path = path
        self.module_name = module_name

    def load(self) -> ModuleMemoState:
        """Parse the module memo file into structured data."""
        if not self.path.exists():
            return ModuleMemoState(module_name=self.module_name)

        text = self.path.read_text(encoding="utf-8")

        return ModuleMemoState(
            module_name=self.module_name,
            roadmap=self._extract_section(text, "Roadmap"),
            sorry_count=self._extract_int(text, "Sorry count"),
            external_claims=self._extract_list(text, "External Claims"),
            compiler_errors=self._extract_list(text, "Compiler Errors"),
            status=self._extract_field(text, "Status"),
        )

    def save(self, state: ModuleMemoState) -> None:
        """Write structured data to the module memo file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self._render(state), encoding="utf-8")

    def _render(self, state: ModuleMemoState) -> str:
        """Render a ModuleMemoState to markdown format."""
        parts: list[str] = []

        parts.append(f"# Module: {state.module_name}\n\n")
        parts.append(f"Status: {state.status}\n")
        parts.append(f"Sorry count: {state.sorry_count}\n")

        parts.append("\n## Roadmap\n\n")
        if state.roadmap:
            parts.append(f"{state.roadmap}\n")

        parts.append("\n## External Claims\n\n")
        for claim in state.external_claims:
            parts.append(f"- {claim}\n")

        parts.append("\n## Compiler Errors\n\n")
        for error in state.compiler_errors:
            parts.append(f"- {error}\n")

        return "".join(parts)

    def update_sorry_count(self, count: int) -> None:
        """Update the sorry count in the module memo."""
        state = self.load()
        state.sorry_count = count
        self.save(state)

    def add_external_claim(self, claim: str) -> None:
        """Add an external claim to the module memo."""
        state = self.load()
        if claim not in state.external_claims:
            state.external_claims.append(claim)
        self.save(state)

    def add_compiler_error(self, error: str) -> None:
        """Add a compiler error to the module memo."""
        state = self.load()
        if error not in state.compiler_errors:
            state.compiler_errors.append(error)
        self.save(state)

    # ------------------------------------------------------------------
    # Parsing Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_section(text: str, heading: str) -> str:
        """Extract content under a ## heading."""
        pattern = re.compile(
            rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_field(text: str, field_name: str) -> str:
        """Extract a field value like 'Status: ...' from text."""
        pattern = re.compile(
            rf"^{re.escape(field_name)}:\s*(.+)$", re.MULTILINE
        )
        match = pattern.search(text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_int(text: str, field_name: str) -> int:
        """Extract an integer field value."""
        pattern = re.compile(
            rf"^{re.escape(field_name)}:\s*(\d+)", re.MULTILINE
        )
        match = pattern.search(text)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _extract_list(text: str, heading: str) -> list[str]:
        """Extract a bulleted list under a ## heading."""
        pattern = re.compile(
            rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(text)
        if not match:
            return []

        items: list[str] = []
        for line in match.group(1).strip().splitlines():
            line = line.strip()
            if line.startswith("- "):
                items.append(line[2:].strip())
        return items
