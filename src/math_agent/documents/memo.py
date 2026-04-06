"""MEMO document management - compressed research state that survives context resets.

The canonical state is stored in ``MEMO.json``.  A human-readable
``MEMO.md`` is rendered alongside for debugging and LLM context injection.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RoadmapStep:
    """A single step in the current roadmap."""

    step_index: int
    description: str
    status: str  # UNPROVED / PROVED / PARTIALLY_PROVED / FAILED / IN_PROGRESS
    result: str | None = None
    lean_status: str | None = None  # null / statement_ok / sketch_ok / proved

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
    lean_compiled: bool = False


@dataclass
class StepFailure:
    """Diagnosis of why a specific step failed."""

    step_index: int
    description: str
    diagnosis: str  # LOGICAL_GAP | FALSE_PROPOSITION | INSUFFICIENT_TECHNIQUE | UNCLEAR
    explanation: str  # detailed explanation of WHY it failed
    false_claim: str = ""  # if FALSE_PROPOSITION: the specific claim that is false

    VALID_DIAGNOSES = frozenset({
        "LOGICAL_GAP",
        "FALSE_PROPOSITION",
        "INSUFFICIENT_TECHNIQUE",
        "UNCLEAR",
    })


@dataclass
class ArchivedRoadmap:
    """A previous roadmap that was abandoned or completed."""

    name: str
    approach: str
    failure_reason: str
    achieved: list[str] = field(default_factory=list)
    lesson: str = ""
    failed_steps: list[StepFailure] = field(default_factory=list)


@dataclass
class RunnerUpRoadmap:
    """An unchosen roadmap stored for fallback."""

    approach: str
    steps: list[str] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class HandoffPacket:
    """Structured handoff for context resets (Layer 4 compression).

    Captures the agent's working state at the moment of a full context
    renewal so the next session can resume precisely instead of
    re-deriving everything from the prose MEMO.
    """

    next_action: str = ""
    open_questions: list[str] = field(default_factory=list)
    current_strategy: str = ""
    blockers: list[str] = field(default_factory=list)
    confidence: float = 0.5
    context_tokens_before_reset: int = 0


@dataclass
class MemoState:
    """The full parsed state of a MEMO document."""

    current_roadmap: list[RoadmapStep] = field(default_factory=list)
    proved_propositions: list[ProvedProposition] = field(default_factory=list)
    refuted_propositions: list[StepFailure] = field(default_factory=list)
    previous_roadmaps: list[ArchivedRoadmap] = field(default_factory=list)
    runner_up_roadmaps: list[RunnerUpRoadmap] = field(default_factory=list)
    handoff: HandoffPacket | None = None

    # ------------------------------------------------------------------
    # JSON serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dict suitable for ``json.dumps``."""
        return {
            "current_roadmap": [
                {
                    "step_index": s.step_index,
                    "description": s.description,
                    "status": s.status,
                    "result": s.result,
                    "lean_status": s.lean_status,
                }
                for s in self.current_roadmap
            ],
            "proved_propositions": [
                {
                    "prop_id": p.prop_id,
                    "statement": p.statement,
                    "source": p.source,
                    "lean_compiled": p.lean_compiled,
                }
                for p in self.proved_propositions
            ],
            "refuted_propositions": [
                {
                    "step_index": r.step_index,
                    "description": r.description,
                    "diagnosis": r.diagnosis,
                    "explanation": r.explanation,
                    "false_claim": r.false_claim,
                }
                for r in self.refuted_propositions
            ],
            "previous_roadmaps": [
                {
                    "name": r.name,
                    "approach": r.approach,
                    "failure_reason": r.failure_reason,
                    "achieved": r.achieved,
                    "lesson": r.lesson,
                    "failed_steps": [
                        {
                            "step_index": f.step_index,
                            "description": f.description,
                            "diagnosis": f.diagnosis,
                            "explanation": f.explanation,
                            "false_claim": f.false_claim,
                        }
                        for f in r.failed_steps
                    ],
                }
                for r in self.previous_roadmaps
            ],
            "runner_up_roadmaps": [
                {
                    "approach": r.approach,
                    "steps": r.steps,
                    "reasoning": r.reasoning,
                }
                for r in self.runner_up_roadmaps
            ],
            "handoff": asdict(self.handoff) if self.handoff else None,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoState:
        """Reconstruct from a plain dict (e.g. from ``json.loads``)."""
        current_roadmap = [
            RoadmapStep(
                step_index=s["step_index"],
                description=s["description"],
                status=s["status"],
                result=s.get("result"),
                lean_status=s.get("lean_status"),
            )
            for s in data.get("current_roadmap", [])
        ]

        proved_propositions = [
            ProvedProposition(
                prop_id=p["prop_id"],
                statement=p["statement"],
                source=p["source"],
                lean_compiled=p.get("lean_compiled", False),
            )
            for p in data.get("proved_propositions", [])
        ]

        refuted_propositions = [
            StepFailure(
                step_index=r.get("step_index", 0),
                description=r.get("description", ""),
                diagnosis=r.get("diagnosis", "UNCLEAR"),
                explanation=r.get("explanation", ""),
                false_claim=r.get("false_claim", ""),
            )
            for r in data.get("refuted_propositions", [])
        ]

        previous_roadmaps = [
            ArchivedRoadmap(
                name=r["name"],
                approach=r["approach"],
                failure_reason=r["failure_reason"],
                achieved=r.get("achieved", []),
                lesson=r.get("lesson", ""),
                failed_steps=[
                    StepFailure(
                        step_index=f.get("step_index", 0),
                        description=f.get("description", ""),
                        diagnosis=f.get("diagnosis", "UNCLEAR"),
                        explanation=f.get("explanation", ""),
                        false_claim=f.get("false_claim", ""),
                    )
                    for f in r.get("failed_steps", [])
                ],
            )
            for r in data.get("previous_roadmaps", [])
        ]

        runner_up_roadmaps = [
            RunnerUpRoadmap(
                approach=r.get("approach", ""),
                steps=r.get("steps", []),
                reasoning=r.get("reasoning", ""),
            )
            for r in data.get("runner_up_roadmaps", [])
        ]

        handoff_raw = data.get("handoff")
        handoff = HandoffPacket(**handoff_raw) if handoff_raw else None

        return cls(
            current_roadmap=current_roadmap,
            proved_propositions=proved_propositions,
            refuted_propositions=refuted_propositions,
            previous_roadmaps=previous_roadmaps,
            runner_up_roadmaps=runner_up_roadmaps,
            handoff=handoff,
        )

    @classmethod
    def from_json(cls, text: str) -> MemoState:
        """Deserialize from a JSON string."""
        return cls.from_dict(json.loads(text))


# ---------------------------------------------------------------------------
# Memo manager
# ---------------------------------------------------------------------------

class Memo:
    """Manages the MEMO state files.

    Canonical state lives in ``MEMO.json``.  ``MEMO.md`` is rendered as a
    human-readable view (and injected into LLM context).  Legacy
    ``MEMO.md``-only files are migrated transparently on first load.
    """

    def __init__(self, path: Path) -> None:
        # *path* may point to either ``MEMO.md`` or ``MEMO.json``.
        # We normalise to use the stem to derive both paths.
        if path.suffix == ".json":
            self.json_path = path
            self.md_path = path.with_suffix(".md")
        else:
            self.md_path = path
            self.json_path = path.with_suffix(".json")

        # Public alias kept for backward-compat (some callers read `memo.path`)
        self.path = self.md_path

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> MemoState:
        """Load the canonical ``MEMO.json``, falling back to ``MEMO.md``
        for backward compatibility with runs created before P3.
        """
        if self.json_path.exists():
            try:
                return MemoState.from_json(
                    self.json_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, KeyError, TypeError):
                pass  # corrupted JSON -- fall through to markdown

        if self.md_path.exists():
            return self._load_from_markdown(
                self.md_path.read_text(encoding="utf-8")
            )

        return MemoState()

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------

    def save(self, state: MemoState) -> None:
        """Write both ``MEMO.json`` (canonical) and ``MEMO.md`` (render)."""
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        self.json_path.write_text(state.to_json(), encoding="utf-8")
        self.md_path.write_text(self._render_md(state), encoding="utf-8")

    # ------------------------------------------------------------------
    # Incremental Updates
    # ------------------------------------------------------------------

    def set_current_roadmap(self, steps: list[RoadmapStep]) -> None:
        """Set a new current roadmap, preserving other sections."""
        state = self.load()
        state.current_roadmap = steps
        self.save(state)

    def append_step_result(
        self, step_index: int, status: str, brief_result: str
    ) -> None:
        """Update the status and result of a specific step."""
        if status not in RoadmapStep.VALID_STATUSES:
            raise ValueError(f"Invalid status {status!r}")
        state = self.load()
        for step in state.current_roadmap:
            if step.step_index == step_index:
                step.status = status
                step.result = brief_result
                break
        self.save(state)

    def add_proved_proposition(
        self, prop_id: str, statement: str, source: str
    ) -> None:
        """Add a proved proposition to the MEMO."""
        state = self.load()
        # Avoid duplicates
        existing_ids = {p.prop_id for p in state.proved_propositions}
        if prop_id not in existing_ids:
            state.proved_propositions.append(
                ProvedProposition(prop_id, statement, source)
            )
        self.save(state)

    def archive_roadmap(
        self,
        roadmap_name: str,
        approach: str,
        failure_reason: str,
        achieved: list[str],
        lesson: str,
        failed_steps: list[StepFailure] | None = None,
    ) -> None:
        """Move the current roadmap to Previous Roadmaps and clear it."""
        state = self.load()
        state.previous_roadmaps.append(
            ArchivedRoadmap(
                name=roadmap_name,
                approach=approach,
                failure_reason=failure_reason,
                achieved=achieved,
                lesson=lesson,
                failed_steps=failed_steps or [],
            )
        )
        state.current_roadmap = []
        self.save(state)

    def add_refuted_proposition(self, failure: StepFailure) -> None:
        """Record a refuted proposition so future roadmaps avoid it."""
        state = self.load()
        # Avoid duplicates by checking false_claim
        existing = {rp.false_claim for rp in state.refuted_propositions if rp.false_claim}
        if failure.false_claim and failure.false_claim not in existing:
            state.refuted_propositions.append(failure)
            self.save(state)

    def store_runner_ups(self, roadmaps: list[dict]) -> None:
        """Store runner-up roadmaps (the ones not chosen on first attempt)."""
        state = self.load()
        state.runner_up_roadmaps = [
            RunnerUpRoadmap(
                approach=r.get("approach", ""),
                steps=r.get("steps", []),
                reasoning=r.get("reasoning", ""),
            )
            for r in roadmaps
        ]
        self.save(state)

    def pop_runner_up(self) -> RunnerUpRoadmap | None:
        """Remove and return the first runner-up roadmap, or None."""
        state = self.load()
        if not state.runner_up_roadmaps:
            return None
        runner_up = state.runner_up_roadmaps.pop(0)
        self.save(state)
        return runner_up

    def set_handoff(self, handoff: HandoffPacket) -> None:
        """Store a handoff packet (used during Layer 4 compression)."""
        state = self.load()
        state.handoff = handoff
        self.save(state)

    def clear_handoff(self) -> None:
        """Clear the handoff packet after it has been consumed."""
        state = self.load()
        if state.handoff is not None:
            state.handoff = None
            self.save(state)

    # ------------------------------------------------------------------
    # Markdown rendering (human-readable + LLM context)
    # ------------------------------------------------------------------

    @staticmethod
    def _render_md(state: MemoState) -> str:
        """Render a MemoState to the MEMO.md format."""
        parts: list[str] = []

        # Current Roadmap
        parts.append("## Current Roadmap\n")
        if state.current_roadmap:
            for step in state.current_roadmap:
                line = f"Step {step.step_index}: {step.description} ... [{step.status}]"
                if step.result:
                    line += f"\n  Result: {step.result}"
                if step.lean_status:
                    line += f"  (lean: {step.lean_status})"
                parts.append(line + "\n")
        else:
            parts.append("(none)\n")

        # Proved Propositions
        parts.append("\n## Proved Propositions (reusable across roadmaps)\n")
        if state.proved_propositions:
            for prop in state.proved_propositions:
                lean_tag = " [lean: compiled]" if prop.lean_compiled else ""
                parts.append(
                    f"- {prop.prop_id}: {prop.statement} ({prop.source}){lean_tag}\n"
                )
        else:
            parts.append("(none yet)\n")

        # Refuted Propositions (DO NOT RETRY)
        if state.refuted_propositions:
            parts.append("\n## Refuted Propositions (DO NOT RETRY these claims)\n")
            for rp in state.refuted_propositions:
                parts.append(f"- FALSE: {rp.false_claim or rp.description}\n")
                parts.append(f"  Reason: {rp.explanation}\n")

        # Previous Roadmaps
        parts.append("\n## Previous Roadmaps\n")
        if state.previous_roadmaps:
            for rm in state.previous_roadmaps:
                parts.append(f"### {rm.name}\n")
                parts.append(f"Approach: {rm.approach}\n")
                parts.append(f"Failed because: {rm.failure_reason}\n")
                parts.append(f"Achieved: {', '.join(rm.achieved) if rm.achieved else '(none)'}\n")
                if rm.failed_steps:
                    parts.append("Step failure details:\n")
                    for fs in rm.failed_steps:
                        diag_label = {
                            "FALSE_PROPOSITION": "FALSE CLAIM",
                            "LOGICAL_GAP": "LOGICAL GAP",
                            "INSUFFICIENT_TECHNIQUE": "TECHNIQUE INSUFFICIENT",
                            "UNCLEAR": "UNCLEAR",
                        }.get(fs.diagnosis, fs.diagnosis)
                        parts.append(
                            f"  - Step {fs.step_index} [{diag_label}]: {fs.explanation}\n"
                        )
                        if fs.false_claim:
                            parts.append(
                                f"    DO NOT RETRY: \"{fs.false_claim}\"\n"
                            )
                parts.append(f"Key lesson: {rm.lesson}\n\n")
        else:
            parts.append("(none yet)\n")

        # Runner-up Roadmaps
        if state.runner_up_roadmaps:
            parts.append("\n## Runner-up Roadmaps\n")
            for i, ru in enumerate(state.runner_up_roadmaps, 1):
                parts.append(f"### Runner-up {i}\n")
                parts.append(f"Approach: {ru.approach}\n")
                if ru.steps:
                    for j, s in enumerate(ru.steps, 1):
                        parts.append(f"  Step {j}: {s}\n")
                parts.append(f"Reasoning: {ru.reasoning}\n\n")

        # Handoff
        if state.handoff:
            h = state.handoff
            parts.append("\n## Handoff (from previous context reset)\n")
            if h.next_action:
                parts.append(f"Next action: {h.next_action}\n")
            if h.current_strategy:
                parts.append(f"Current strategy: {h.current_strategy}\n")
            if h.open_questions:
                parts.append("Open questions:\n")
                for q in h.open_questions:
                    parts.append(f"  - {q}\n")
            if h.blockers:
                parts.append("Blockers:\n")
                for b in h.blockers:
                    parts.append(f"  - {b}\n")
            parts.append(f"Confidence: {h.confidence:.2f}\n")

        return "".join(parts)

    # ------------------------------------------------------------------
    # Legacy markdown parser (backward compat)
    # ------------------------------------------------------------------

    @classmethod
    def _load_from_markdown(cls, text: str) -> MemoState:
        """Parse legacy MEMO.md into structured data."""
        return MemoState(
            current_roadmap=cls._parse_current_roadmap(text),
            proved_propositions=cls._parse_proved_propositions(text),
            previous_roadmaps=cls._parse_previous_roadmaps(text),
        )

    @staticmethod
    def _parse_current_roadmap(text: str) -> list[RoadmapStep]:
        section = Memo._extract_section(text, "Current Roadmap")
        if not section:
            return []
        steps: list[RoadmapStep] = []
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

    @staticmethod
    def _parse_proved_propositions(text: str) -> list[ProvedProposition]:
        section = Memo._extract_section(text, "Proved Propositions")
        if not section:
            return []
        props: list[ProvedProposition] = []
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

    @staticmethod
    def _parse_previous_roadmaps(text: str) -> list[ArchivedRoadmap]:
        section = Memo._extract_section(text, "Previous Roadmaps")
        if not section:
            return []
        roadmaps: list[ArchivedRoadmap] = []
        roadmap_blocks = re.split(r"###\s+", section)
        for block in roadmap_blocks:
            block = block.strip()
            if not block:
                continue
            header_match = re.match(r"(.+?)(?:\s+\([^)]*\))?\s*\n", block)
            if not header_match:
                continue
            name = header_match.group(1).strip()
            body = block[header_match.end():]
            approach = Memo._extract_field(body, "Approach")
            failure_reason = Memo._extract_field(body, "Failed because")
            achieved_str = Memo._extract_field(body, "Achieved")
            lesson = Memo._extract_field(body, "Key lesson")
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
        pattern = re.compile(
            rf"^##\s+{re.escape(heading)}.*?\n(.*?)(?=^##\s|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(text)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_field(text: str, field_name: str) -> str:
        pattern = re.compile(
            rf"^{re.escape(field_name)}:\s*(.+)$", re.MULTILINE
        )
        match = pattern.search(text)
        return match.group(1).strip() if match else ""
