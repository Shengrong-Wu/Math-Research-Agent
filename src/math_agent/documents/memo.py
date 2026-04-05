"""MEMO document management - compressed research state that survives context resets."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RoadmapStep:
    """A single step in the current roadmap."""

    step_index: int
    description: str
    status: str  # UNPROVED / PROVED / PARTIALLY_PROVED / FAILED / IN_PROGRESS

    VALID_STATUSES = frozenset({
        "UNPROVED",
        "PROVED",
        "PARTIALLY_PROVED",
        "FAILED",
        "IN_PROGRESS",
    })

    def __post_init__(self) -> None:
        if self.status not in self.VALID_STATUSES:
            raise ValueError(
                f"Invalid status {self.status!r}; "
                f"must be one of {sorted(self.VALID_STATUSES)}"
            )


@dataclass
class ProvedProposition:
    """A proved proposition reusable across roadmaps."""

    prop_id: str
    statement: str
    source: str  # e.g. "proved in Roadmap X, step Y"


@dataclass
class ArchivedRoadmap:
    """A previous roadmap that was abandoned or completed."""

    name: str
    approach: str
    failure_reason: str
    achieved: list[str]
    lesson: str


@dataclass
class MemoState:
    """The full parsed state of a MEMO document."""

    current_roadmap: list[RoadmapStep] = field(default_factory=list)
    proved_propositions: list[ProvedProposition] = field(default_factory=list)
    previous_roadmaps: list[ArchivedRoadmap] = field(default_factory=list)


class Memo:
    """Manages the MEMO.md document - the compressed research state."""

    def __init__(self, path: Path) -> None:
        self.path = path

    # ------------------------------------------------------------------
    # Loading / Parsing
    # ------------------------------------------------------------------

    def load(self) -> MemoState:
        """Parse MEMO.md into structured data."""
        if not self.path.exists():
            return MemoState()

        text = self.path.read_text(encoding="utf-8")
        return MemoState(
            current_roadmap=self._parse_current_roadmap(text),
            proved_propositions=self._parse_proved_propositions(text),
            previous_roadmaps=self._parse_previous_roadmaps(text),
        )

    def _parse_current_roadmap(self, text: str) -> list[RoadmapStep]:
        """Extract current roadmap steps from memo text."""
        section = self._extract_section(text, "Current Roadmap")
        if not section:
            return []

        steps: list[RoadmapStep] = []
        # Match lines like: Step 1: description ... [STATUS]
        pattern = re.compile(
            r"Step\s+(\d+):\s+(.+?)\s+\[([A-Z_]+)\]"
        )
        for match in pattern.finditer(section):
            step_index = int(match.group(1))
            description = match.group(2).strip().rstrip(".")
            status = match.group(3)
            if status in RoadmapStep.VALID_STATUSES:
                steps.append(RoadmapStep(step_index, description, status))
        return steps

    def _parse_proved_propositions(self, text: str) -> list[ProvedProposition]:
        """Extract proved propositions from memo text."""
        section = self._extract_section(text, "Proved Propositions")
        if not section:
            return []

        props: list[ProvedProposition] = []
        # Match lines like: - P1: statement (proved in Roadmap X, step Y)
        pattern = re.compile(
            r"-\s+(P\d+):\s+(.+?)\s+\(([^)]+)\)"
        )
        for match in pattern.finditer(section):
            props.append(ProvedProposition(
                prop_id=match.group(1),
                statement=match.group(2).strip(),
                source=match.group(3).strip(),
            ))
        return props

    def _parse_previous_roadmaps(self, text: str) -> list[ArchivedRoadmap]:
        """Extract previous roadmaps from memo text."""
        section = self._extract_section(text, "Previous Roadmaps")
        if not section:
            return []

        roadmaps: list[ArchivedRoadmap] = []
        # Split on ### headers for individual roadmaps
        roadmap_blocks = re.split(r"###\s+", section)
        for block in roadmap_blocks:
            block = block.strip()
            if not block:
                continue

            # Parse header line: "Roadmap A (abandoned, round N)"
            header_match = re.match(r"(.+?)(?:\s+\([^)]*\))?\s*\n", block)
            if not header_match:
                continue

            name = header_match.group(1).strip()
            body = block[header_match.end():]

            approach = self._extract_field(body, "Approach")
            failure_reason = self._extract_field(body, "Failed because")
            achieved_str = self._extract_field(body, "Achieved")
            lesson = self._extract_field(body, "Key lesson")

            achieved = [
                a.strip() for a in achieved_str.split(",")
            ] if achieved_str else []

            roadmaps.append(ArchivedRoadmap(
                name=name,
                approach=approach,
                failure_reason=failure_reason,
                achieved=achieved,
                lesson=lesson,
            ))
        return roadmaps

    @staticmethod
    def _extract_section(text: str, heading: str) -> str | None:
        """Extract content under a ## heading, up to the next ## heading."""
        pattern = re.compile(
            rf"^##\s+{re.escape(heading)}.*?\n(.*?)(?=^##\s|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(text)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_field(text: str, field_name: str) -> str:
        """Extract a field value like 'Approach: ...' from text."""
        pattern = re.compile(
            rf"^{re.escape(field_name)}:\s*(.+)$", re.MULTILINE
        )
        match = pattern.search(text)
        return match.group(1).strip() if match else ""

    # ------------------------------------------------------------------
    # Saving / Writing
    # ------------------------------------------------------------------

    def save(self, state: MemoState) -> None:
        """Write structured data to MEMO.md (full rewrite)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self._render(state), encoding="utf-8")

    def _render(self, state: MemoState) -> str:
        """Render a MemoState to the MEMO.md format."""
        parts: list[str] = []

        # Current Roadmap
        parts.append("## Current Roadmap\n")
        for step in state.current_roadmap:
            parts.append(
                f"Step {step.step_index}: {step.description} ... [{step.status}]\n"
            )

        # Proved Propositions
        parts.append("\n## Proved Propositions (reusable across roadmaps)\n")
        for prop in state.proved_propositions:
            parts.append(f"- {prop.prop_id}: {prop.statement} ({prop.source})\n")

        # Previous Roadmaps
        parts.append("\n## Previous Roadmaps\n")
        for rm in state.previous_roadmaps:
            parts.append(f"### {rm.name}\n")
            parts.append(f"Approach: {rm.approach}\n")
            parts.append(f"Failed because: {rm.failure_reason}\n")
            parts.append(f"Achieved: {', '.join(rm.achieved)}\n")
            parts.append(f"Key lesson: {rm.lesson}\n\n")

        return "".join(parts)

    # ------------------------------------------------------------------
    # Incremental Updates
    # ------------------------------------------------------------------

    def append_step_result(
        self, step_index: int, status: str, brief_result: str
    ) -> None:
        """Cursor-based incremental update: append result to a step.

        Instead of rewriting the entire file, this appends/updates in place.
        """
        if status not in RoadmapStep.VALID_STATUSES:
            raise ValueError(f"Invalid status {status!r}")

        if not self.path.exists():
            return

        text = self.path.read_text(encoding="utf-8")

        # Find the step line and update its status
        pattern = re.compile(
            rf"(Step\s+{step_index}:\s+.+?)\s+\[([A-Z_]+)\]"
        )
        match = pattern.search(text)
        if match:
            # Replace the status in the existing line
            old_line = match.group(0)
            new_line = f"{match.group(1)} [{status}]"
            text = text.replace(old_line, new_line, 1)

            # Append the brief result right after the step line
            result_line = f"  Result: {brief_result}\n"
            insert_pos = text.find(new_line) + len(new_line)
            # Check if there's already a newline
            if insert_pos < len(text) and text[insert_pos] == "\n":
                insert_pos += 1
            text = text[:insert_pos] + result_line + text[insert_pos:]

            self.path.write_text(text, encoding="utf-8")

    def add_proved_proposition(
        self, prop_id: str, statement: str, source: str
    ) -> None:
        """Add a proved proposition to the MEMO."""
        if not self.path.exists():
            # Create with just this proposition
            state = MemoState(
                proved_propositions=[
                    ProvedProposition(prop_id, statement, source)
                ]
            )
            self.save(state)
            return

        text = self.path.read_text(encoding="utf-8")
        prop_line = f"- {prop_id}: {statement} ({source})\n"

        # Find the Proved Propositions section and append
        section_pattern = re.compile(
            r"(##\s+Proved Propositions.*?\n)(.*?)(?=\n##\s|\Z)",
            re.DOTALL,
        )
        match = section_pattern.search(text)
        if match:
            insert_pos = match.end()
            # Insert before the next section
            text = text[:insert_pos] + prop_line + text[insert_pos:]
        else:
            # No section exists yet; append one before Previous Roadmaps
            prev_match = re.search(r"\n##\s+Previous Roadmaps", text)
            if prev_match:
                insert_pos = prev_match.start()
            else:
                insert_pos = len(text)
            section = (
                "\n## Proved Propositions (reusable across roadmaps)\n"
                + prop_line
            )
            text = text[:insert_pos] + section + text[insert_pos:]

        self.path.write_text(text, encoding="utf-8")

    def archive_roadmap(
        self,
        roadmap_name: str,
        approach: str,
        failure_reason: str,
        achieved: list[str],
        lesson: str,
    ) -> None:
        """Move the current roadmap to Previous Roadmaps and clear it."""
        state = self.load()

        archived = ArchivedRoadmap(
            name=roadmap_name,
            approach=approach,
            failure_reason=failure_reason,
            achieved=achieved,
            lesson=lesson,
        )
        state.previous_roadmaps.append(archived)
        state.current_roadmap = []
        self.save(state)

    def set_current_roadmap(self, steps: list[RoadmapStep]) -> None:
        """Set a new current roadmap, preserving other sections."""
        state = self.load()
        state.current_roadmap = steps
        self.save(state)
