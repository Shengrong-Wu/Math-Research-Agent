"""NOTES document management - detailed proof record."""

from __future__ import annotations

import re
from pathlib import Path


class Notes:
    """Manages the NOTES.md document - the detailed proof record."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> str:
        """Read full notes content."""
        if not self.path.exists():
            return ""
        return self.path.read_text(encoding="utf-8")

    def append_step_proof(
        self, step_index: int, step_description: str, proof_detail: str
    ) -> None:
        """Append a detailed proof for a roadmap step.

        Each step proof is formatted as a section with the step index
        and description as a header, followed by the proof detail.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)

        entry = (
            f"\n## Step {step_index}: {step_description}\n\n"
            f"{proof_detail}\n"
        )

        with self.path.open("a", encoding="utf-8") as f:
            f.write(entry)

    def get_step_proof(self, step_index: int) -> str | None:
        """Find proof text for a specific step by its index.

        Searches the notes for a section headed "## Step {step_index}: ..."
        and returns its content.

        Returns None if the step is not found in the notes.
        """
        if not self.path.exists():
            return None

        text = self.path.read_text(encoding="utf-8")

        pattern = re.compile(
            rf"^## Step {step_index}:.*?\n(.*?)(?=^## Step \d+:|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(text)
        if match:
            return match.group(0).strip()

        return None

    def get_proposition_proof(self, prop_id: str) -> str | None:
        """Find proof text for a specific proposition by its ID.

        Searches the notes for any section or reference mentioning the
        proposition ID and returns the surrounding proof content.

        Returns None if the proposition is not found in the notes.
        """
        if not self.path.exists():
            return None

        text = self.path.read_text(encoding="utf-8")

        # First try: look for a dedicated section for this proposition
        # e.g. "## P1: ..." or "### P1: ..."
        section_pattern = re.compile(
            rf"^##+ .*{re.escape(prop_id)}[:\s].*?\n(.*?)(?=^##|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = section_pattern.search(text)
        if match:
            return match.group(0).strip()

        # Second try: find any step section that references this proposition
        step_pattern = re.compile(
            rf"^## Step \d+:.*?\n(.*?)(?=^## Step \d+:|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        for step_match in step_pattern.finditer(text):
            section_text = step_match.group(0)
            if prop_id in section_text:
                return section_text.strip()

        return None
