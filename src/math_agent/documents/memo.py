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
# Proposition-source parsing helpers (Fix 4 — cross-session quarantine)
# ---------------------------------------------------------------------------

# Phase1Runner writes proposition sources as
#   - ``f"Roadmap {n}, step {k}"`` when recorded during ordinary proving
#   - ``f"Lemma queue, step {k}"`` when recorded from the lemma-queue path
# The cross-session quarantine needs to parse these back out so it can decide
# which archived roadmap each proposition belongs to. Anything that doesn't
# match either shape is treated as "unknown origin" and left untouched.

_PROP_SOURCE_ROADMAP_RE = re.compile(
    r"^\s*Roadmap\s+(?P<roadmap>[^,]+?)\s*,\s*step\s+(?P<step>\d+)\s*$"
)
_PROP_SOURCE_LEMMA_QUEUE_RE = re.compile(
    r"^\s*Lemma\s+queue\s*,\s*step\s+(?P<step>\d+)\s*$"
)


def _parse_prop_source(source: str) -> tuple[str | None, int | None]:
    """Parse a ``ProvedProposition.source`` string.

    Returns ``(roadmap_name, step_index)`` where either component may be None
    if the source shape is unrecognised. For lemma-queue sources the roadmap
    component is the literal string ``"Lemma queue"``.
    """
    if not source:
        return (None, None)
    match = _PROP_SOURCE_ROADMAP_RE.match(source)
    if match:
        # ``"Roadmap 1"`` or ``"Roadmap Alpha"`` — we normalise the full
        # prefix so it can be matched against ArchivedRoadmap.name.
        return (f"Roadmap {match.group('roadmap').strip()}", int(match.group("step")))
    match = _PROP_SOURCE_LEMMA_QUEUE_RE.match(source)
    if match:
        return ("Lemma queue", int(match.group("step")))
    return (None, None)


# Heuristics for detecting a review-rejected archived roadmap. We prefer the
# explicit ``ArchivedRoadmap.review_rejected`` flag when it is present; the
# string heuristic exists because older MEMO.json files on disk (from runs
# that predate Fix 3) cannot know about the flag and must still be recognised
# when a new session loads them.
_REVIEW_REJECTED_MARKERS = (
    "review found gaps",
    "review rejected",
    "review-rejected",
    "review confidence",
)

_FAILURE_NORMALIZE_WS_RE = re.compile(r"\s+")
_FAILURE_NORMALIZE_NUM_RE = re.compile(r"\b(?:roadmap|step)\s+\d+\b", re.IGNORECASE)


def _normalize_failure_text(text: str, *, limit: int = 120) -> str:
    """Normalize failure text for conservative motif grouping."""
    collapsed = _FAILURE_NORMALIZE_WS_RE.sub(" ", text or "").strip().lower()
    collapsed = _FAILURE_NORMALIZE_NUM_RE.sub("", collapsed)
    collapsed = _FAILURE_NORMALIZE_WS_RE.sub(" ", collapsed).strip(" ;,.-")
    return collapsed[:limit]


def _is_review_rejected(archive: ArchivedRoadmap) -> bool:
    """Return True if *archive* looks like a review-rejected roadmap."""
    if getattr(archive, "review_rejected", False):
        return True
    haystack = f"{archive.failure_reason or ''}\n{archive.lesson or ''}".lower()
    return any(marker in haystack for marker in _REVIEW_REJECTED_MARKERS)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RoadmapStep:
    """A single step in the current roadmap."""

    step_index: int
    description: str
    status: str  # UNPROVED / PROVED / PARTIALLY_PROVED / FAILED / IN_PROGRESS
    roadmap_id: str = ""
    step_id: str = ""
    result: str | None = None
    lean_status: str | None = None  # null / statement_ok / sketch_ok / proved

    # --- P6: Step-level checkpointing ---
    claim: str = ""                  # the specific claim this step proves
    proof_text: str = ""             # full proof text (from NOTES)
    verification_result: str = ""    # VERIFIED / INVALID / ""
    lemma_dependencies: list[str] = field(default_factory=list)   # prop_ids used
    downstream_obligations: list[str] = field(default_factory=list)
    debt: str = "none"               # none / temporary_hole / missing_api / textbook_theorem / hidden_axiom

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
    """A proved proposition reusable across roadmaps.

    *suspect* is set when the roadmap that produced this proposition was
    later rejected by the review agent. Suspect propositions remain in the
    MEMO so future planners know what was *attempted*, but they are rendered
    under a separate "Suspect Propositions" heading that explicitly warns
    against invoking them as premises without re-proving from scratch.
    """

    prop_id: str
    statement: str
    source: str  # e.g. "Roadmap X, step Y"
    source_roadmap_id: str = ""
    source_step_id: str = ""
    note_id: str = ""
    lean_compiled: bool = False
    suspect: bool = False


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
    """A previous roadmap that was abandoned or completed.

    *review_rejected* is True when the roadmap was archived because the
    review agent found gaps in the compiled proof. Cross-session quarantine
    uses this flag (preferred over fragile string matching on
    ``failure_reason``) to decide whether propositions sourced from this
    roadmap should be treated as suspect in subsequent sessions.
    """

    name: str
    approach: str
    failure_reason: str
    roadmap_id: str = ""
    achieved: list[str] = field(default_factory=list)
    lesson: str = ""
    failed_steps: list[StepFailure] = field(default_factory=list)
    artifact_summaries: list[str] = field(default_factory=list)
    review_rejected: bool = False


@dataclass
class RunnerUpRoadmap:
    """An unchosen roadmap stored for fallback."""

    approach: str
    steps: list[str] = field(default_factory=list)
    step_obligations: list[list[str]] = field(default_factory=list)
    macro_steps: list[dict[str, Any]] = field(default_factory=list)
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
    roadmap_number: int = 0
    roadmap_id: str = ""
    current_step_index: int = 0
    current_step_id: str = ""
    proved_steps: list[int] = field(default_factory=list)
    remaining_steps: list[int] = field(default_factory=list)
    failed_steps: list[int] = field(default_factory=list)
    reusable_prop_ids: list[str] = field(default_factory=list)
    proof_keys: list[str] = field(default_factory=list)
    proof_note_ids: list[str] = field(default_factory=list)
    proof_summaries: list[str] = field(default_factory=list)
    recent_diagnoses: list[str] = field(default_factory=list)
    active_step_label: str = ""
    open_obligations: list[str] = field(default_factory=list)


@dataclass
class FailureLedgerEntry:
    key: str
    source_roadmap_id: str = ""
    count: int = 0
    attempts: list[int] = field(default_factory=list)
    first_attempt: int = 0
    last_attempt: int = 0
    diagnosis: str = ""
    blocked_claim: str = ""
    motif: str = ""
    example_reason: str = ""
    do_not_retry_guidance: str = ""
    source_kind: str = ""
    linked_strategies: list[str] = field(default_factory=list)


@dataclass
class ObligationRecord:
    obligation_id: str
    label: str = ""
    status: str = "open"
    supporting_steps: list[int] = field(default_factory=list)
    supporting_claim_ids: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class FrontierState:
    roadmap_number: int = 0
    roadmap_id: str = ""
    active_step_index: int = 0
    active_step_id: str = ""
    active_step_label: str = ""
    next_step_indices: list[int] = field(default_factory=list)
    current_blockers: list[str] = field(default_factory=list)
    needed_proof_keys: list[str] = field(default_factory=list)
    open_obligations: list[str] = field(default_factory=list)
    last_update_event: str = ""


@dataclass
class ProofIndexEntry:
    prop_id: str
    statement: str
    source: str
    source_roadmap_id: str = ""
    source_step_id: str = ""
    suspect: bool = False
    summary: str = ""
    note_key: str = ""
    note_id: str = ""
    dependencies: list[str] = field(default_factory=list)


# --- v3: lightweight knowledge graph memory ---

VALID_KG_NODE_TYPES = frozenset({"claim", "strategy", "obstruction"})
VALID_KG_EDGE_TYPES = frozenset({"depends_on", "refutes", "variant_of"})
VALID_KG_STATUSES = frozenset({
    "proposed",
    "argued",
    "review_supported",
    "cross_attempt_reused",
    "suspect",
    "refuted",
})
KG_STATUS_RANK = {
    "proposed": 0,
    "argued": 1,
    "review_supported": 2,
    "cross_attempt_reused": 3,
    "suspect": 4,
    "refuted": 5,
}


@dataclass
class KGNode:
    node_id: str
    node_type: str
    statement: str
    status: str
    source_attempt: int
    source_step: int | None
    evidence_summary: str
    reusable: bool
    source_roadmap_id: str = ""
    source_step_id: str = ""
    stale: bool = False
    alias_of: str | None = None


@dataclass
class KGEdge:
    source: str
    target: str
    edge_type: str


@dataclass
class KnowledgeGraph:
    nodes: list[KGNode] = field(default_factory=list)
    edges: list[KGEdge] = field(default_factory=list)

    def get_node(self, node_id: str) -> KGNode | None:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None

    def upsert_node(self, node: KGNode) -> KGNode:
        if node.node_type not in VALID_KG_NODE_TYPES:
            raise ValueError(f"Invalid KG node type {node.node_type!r}")
        if node.status not in VALID_KG_STATUSES:
            raise ValueError(f"Invalid KG status {node.status!r}")
        existing = self.get_node(node.node_id)
        if existing is None:
            self.nodes.append(node)
            return node
        if KG_STATUS_RANK[node.status] >= KG_STATUS_RANK[existing.status]:
            existing.status = node.status
        if node.statement:
            existing.statement = node.statement
        if node.evidence_summary and len(node.evidence_summary) >= len(existing.evidence_summary):
            existing.evidence_summary = node.evidence_summary
        existing.reusable = existing.reusable or node.reusable
        existing.stale = node.stale if node.stale else existing.stale
        if node.alias_of:
            existing.alias_of = node.alias_of
        existing.source_attempt = max(existing.source_attempt, node.source_attempt)
        if node.source_step is not None:
            existing.source_step = node.source_step
        return existing

    def add_edge(self, edge: KGEdge) -> None:
        if edge.edge_type not in VALID_KG_EDGE_TYPES:
            raise ValueError(f"Invalid KG edge type {edge.edge_type!r}")
        for existing in self.edges:
            if (
                existing.source == edge.source
                and existing.target == edge.target
                and existing.edge_type == edge.edge_type
            ):
                return
        self.edges.append(edge)

    def linked_edges(
        self,
        node_ids: set[str],
        *,
        edge_type: str | None = None,
    ) -> list[KGEdge]:
        return [
            edge for edge in self.edges
            if (edge.source in node_ids or edge.target in node_ids)
            and (edge_type is None or edge.edge_type == edge_type)
        ]

    def enforce_active_cap(self, max_active_nodes: int = 100) -> None:
        active = [node for node in self.nodes if not node.stale]
        if len(active) <= max_active_nodes:
            return
        ranked = sorted(
            active,
            key=lambda node: (
                node.reusable,
                -int(node.status in {"suspect", "refuted"}),
                KG_STATUS_RANK.get(node.status, 0),
                node.source_attempt,
                node.source_step or 0,
            ),
            reverse=True,
        )
        keep_ids = {node.node_id for node in ranked[:max_active_nodes]}
        for node in self.nodes:
            if node.node_id not in keep_ids:
                node.stale = True

    def _fit_blocks(self, blocks: list[str], max_chars: int) -> str:
        if max_chars <= 0:
            return ""
        result: list[str] = []
        total = 0
        omitted = 0
        for block in blocks:
            block_len = len(block)
            if total + block_len > max_chars:
                omitted += 1
                continue
            result.append(block)
            total += block_len
        if omitted:
            header = f"(omitted {omitted} graph block(s) due to prompt budget)\n\n"
            if len(header) + total <= max_chars:
                result.insert(0, header)
        return "".join(result).strip()

    def render_for_planner(self, max_chars: int = 15_000) -> str:
        blocks: list[str] = []
        strategies = sorted(
            [n for n in self.nodes if n.node_type == "strategy" and not n.stale],
            key=lambda n: (n.source_attempt, KG_STATUS_RANK.get(n.status, 0)),
            reverse=True,
        )
        obstructions = sorted(
            [n for n in self.nodes if n.node_type == "obstruction" and not n.stale],
            key=lambda n: (n.source_attempt, KG_STATUS_RANK.get(n.status, 0)),
            reverse=True,
        )
        claims = sorted(
            [
                n for n in self.nodes
                if n.node_type == "claim" and not n.stale and n.reusable
            ],
            key=lambda n: (KG_STATUS_RANK.get(n.status, 0), n.source_attempt),
            reverse=True,
        )
        if strategies:
            lines = ["## Strategy Graph\n"]
            for node in strategies:
                lines.append(
                    f"- attempt {node.source_attempt}: {node.statement} [{node.status}]\n"
                )
                if node.evidence_summary:
                    lines.append(f"  summary: {node.evidence_summary}\n")
            blocks.append("".join(lines) + "\n")
        if obstructions:
            lines = ["## Known Obstructions\n"]
            for node in obstructions[:12]:
                lines.append(
                    f"- attempt {node.source_attempt}"
                    + (f", step {node.source_step}" if node.source_step else "")
                    + f": {node.statement} [{node.status}]\n"
                )
                if node.evidence_summary:
                    lines.append(f"  reason: {node.evidence_summary}\n")
            blocks.append("".join(lines) + "\n")
        if claims:
            lines = ["## Reusable Claims\n"]
            for node in claims[:12]:
                lines.append(
                    f"- {node.statement} [{node.status}, attempt {node.source_attempt}]\n"
                )
            blocks.append("".join(lines))
        return self._fit_blocks(blocks, max_chars)

    def render_for_worker(self, query: str, max_chars: int = 10_000) -> str:
        raw_terms = re.findall(r"[A-Za-z0-9_]+", query)
        query_terms = {
            term.lower()
            for term in raw_terms
            if len(term) > 2 or term.isupper()
        }

        def relevance(node: KGNode) -> tuple[int, int, int, int]:
            text = node.statement.lower()
            overlap = sum(1 for term in query_terms if term in text)
            return (
                overlap,
                KG_STATUS_RANK.get(node.status, 0),
                int(node.reusable),
                node.source_attempt,
            )

        nodes = sorted(
            [node for node in self.nodes if not node.stale],
            key=relevance,
            reverse=True,
        )
        top = nodes[:8]
        top_ids = {node.node_id for node in top}
        edges = self.linked_edges(top_ids)
        blocks: list[str] = []
        if top:
            lines = ["## Worker Retrieval\n"]
            for node in top:
                lines.append(
                    f"- {node.node_type}: {node.statement} [{node.status}, attempt {node.source_attempt}]\n"
                )
                if node.node_type == "claim" and node.node_id.startswith("claim_"):
                    lines.append(
                        f"  proof key: {node.node_id.removeprefix('claim_')}\n"
                    )
                if node.evidence_summary:
                    lines.append(f"  note: {node.evidence_summary}\n")
            blocks.append("".join(lines) + "\n")
        if edges:
            lines = ["## Nearby Dependencies\n"]
            for edge in edges[:12]:
                lines.append(f"- {edge.source} --{edge.edge_type}--> {edge.target}\n")
            blocks.append("".join(lines))
        return self._fit_blocks(blocks, max_chars)

    def select_relevant_claim_keys(
        self,
        query: str,
        *,
        max_items: int = 4,
    ) -> list[str]:
        raw_terms = re.findall(r"[A-Za-z0-9_]+", query)
        query_terms = {
            term.lower()
            for term in raw_terms
            if len(term) > 2 or term.isupper()
        }

        def relevance(node: KGNode) -> tuple[int, int, int, int]:
            text = node.statement.lower()
            overlap = sum(1 for term in query_terms if term in text)
            return (
                overlap,
                KG_STATUS_RANK.get(node.status, 0),
                int(node.reusable),
                node.source_attempt,
            )

        claims = sorted(
            [
                node
                for node in self.nodes
                if (
                    node.node_type == "claim"
                    and node.reusable
                    and not node.stale
                    and node.node_id.startswith("claim_")
                    and node.status not in {"suspect", "refuted"}
                )
            ],
            key=relevance,
            reverse=True,
        )
        return [
            node.node_id.removeprefix("claim_")
            for node in claims[:max_items]
        ]

    def render_for_reviewer(
        self,
        cited_claims: list[str] | None = None,
        max_chars: int = 5_000,
    ) -> str:
        cited = cited_claims or []
        claim_terms = " ".join(cited).lower()
        matched = [
            node for node in self.nodes
            if node.node_type == "claim"
            and not node.stale
            and (
                not cited
                or any(part and node.node_id.endswith(part) for part in cited)
                or any(part and part.lower() in node.statement.lower() for part in cited)
                or node.statement.lower() in claim_terms
            )
        ]
        matched = sorted(
            matched,
            key=lambda node: (KG_STATUS_RANK.get(node.status, 0), node.source_attempt),
            reverse=True,
        )
        match_ids = {node.node_id for node in matched}
        refutations = [
            edge for edge in self.linked_edges(match_ids, edge_type="refutes")
            if edge.target in match_ids
        ]
        blocks: list[str] = []
        if matched:
            lines = ["## Claim Trust Summary\n"]
            for node in matched[:10]:
                lines.append(
                    f"- {node.statement} [{node.status}, attempt {node.source_attempt}]\n"
                )
                if node.evidence_summary:
                    lines.append(f"  evidence: {node.evidence_summary}\n")
            blocks.append("".join(lines) + "\n")
        if refutations:
            lines = ["## Direct Refutations\n"]
            for edge in refutations[:10]:
                lines.append(f"- {edge.source} refutes {edge.target}\n")
            blocks.append("".join(lines))
        return self._fit_blocks(blocks, max_chars)


# --- P3: Formal Artifact Ledger ---

VALID_CLAIM_STATUSES = frozenset({
    "conjectured", "experimentally_supported", "informally_justified",
    "lean_statement_checked", "lean_sketch_checked", "lean_fully_checked",
})

VALID_DEBT_LABELS = frozenset({
    "none", "temporary_hole", "missing_api", "textbook_theorem", "hidden_axiom",
})


@dataclass
class FormalArtifact:
    """A typed claim in the proof with formal status tracking."""

    claim: str = ""
    proof_text: str = ""
    claim_status: str = "conjectured"      # one of VALID_CLAIM_STATUSES
    debt_label: str = "none"               # one of VALID_DEBT_LABELS
    lean_statement: str = ""
    lean_sketch: str = ""
    dependencies: list[str] = field(default_factory=list)


# --- P4: Auxiliary Lemma Queue ---

VALID_LEMMA_TYPES = frozenset({
    "sufficiency", "special_case", "interface", "strengthening",
})


@dataclass
class AuxiliaryLemma:
    """An auxiliary lemma queued for proving."""

    lemma_type: str          # one of VALID_LEMMA_TYPES
    statement: str
    source: str              # e.g. "step 3 failure", "falsifier rejection"
    status: str = "pending"  # pending / in_progress / resolved
    unblocks: list[int] = field(default_factory=list)  # step indices


# --- P7: Hierarchical Roadmaps ---

@dataclass
class MacroStep:
    """A macro-step containing sub-steps (two-level roadmap)."""

    index: int
    description: str
    deliverable: str  # named output (not vague theme)
    sub_steps: list[RoadmapStep] = field(default_factory=list)
    status: str = "UNPROVED"  # derived from sub-step statuses

    def update_status(self) -> None:
        """Update status from sub-step statuses."""
        if not self.sub_steps:
            return
        if all(s.status == "PROVED" for s in self.sub_steps):
            self.status = "PROVED"
        elif any(s.status == "FAILED" for s in self.sub_steps):
            self.status = "FAILED"
        elif any(s.status in ("IN_PROGRESS", "PROVED") for s in self.sub_steps):
            self.status = "IN_PROGRESS"
        else:
            self.status = "UNPROVED"


@dataclass
class MemoState:
    """The full parsed state of a MEMO document."""

    current_roadmap_id: str = ""
    current_approach: str = ""
    current_roadmap: list[RoadmapStep] = field(default_factory=list)
    proved_propositions: list[ProvedProposition] = field(default_factory=list)
    refuted_propositions: list[StepFailure] = field(default_factory=list)
    previous_roadmaps: list[ArchivedRoadmap] = field(default_factory=list)
    runner_up_roadmaps: list[RunnerUpRoadmap] = field(default_factory=list)
    handoff: HandoffPacket | None = None

    # --- P3: Formal artifacts ---
    formal_artifacts: list[FormalArtifact] = field(default_factory=list)

    # --- P4: Auxiliary lemma queue ---
    lemma_queue: list[AuxiliaryLemma] = field(default_factory=list)

    # --- P7: Hierarchical roadmap (None = flat mode) ---
    macro_roadmap: list[MacroStep] | None = None

    # --- v3: cross-roadmap DAG-style memory ---
    knowledge_graph: KnowledgeGraph = field(default_factory=KnowledgeGraph)

    # --- v3: repeated-failure aggregation ---
    failure_ledger: list[FailureLedgerEntry] = field(default_factory=list)

    # --- v3: explicit hot working state ---
    obligations: list[ObligationRecord] = field(default_factory=list)
    frontier: FrontierState | None = None
    proof_index: list[ProofIndexEntry] = field(default_factory=list)

    # ------------------------------------------------------------------
    # JSON serialization
    # ------------------------------------------------------------------

    @staticmethod
    def _step_to_dict(s: RoadmapStep) -> dict[str, Any]:
        """Serialize a RoadmapStep to a dict."""
        d: dict[str, Any] = {
            "step_index": s.step_index,
            "description": s.description,
            "status": s.status,
            "roadmap_id": s.roadmap_id,
            "step_id": s.step_id,
            "result": s.result,
            "lean_status": s.lean_status,
        }
        # P6: checkpoint fields (omit when empty for compactness)
        if s.claim:
            d["claim"] = s.claim
        if s.proof_text:
            d["proof_text"] = s.proof_text
        if s.verification_result:
            d["verification_result"] = s.verification_result
        if s.lemma_dependencies:
            d["lemma_dependencies"] = s.lemma_dependencies
        if s.downstream_obligations:
            d["downstream_obligations"] = s.downstream_obligations
        if s.debt != "none":
            d["debt"] = s.debt
        return d

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dict suitable for ``json.dumps``."""
        result: dict[str, Any] = {
            "current_roadmap_id": self.current_roadmap_id,
            "current_approach": self.current_approach,
            "current_roadmap": [
                self._step_to_dict(s) for s in self.current_roadmap
            ],
            "proved_propositions": [
                {
                    "prop_id": p.prop_id,
                    "statement": p.statement,
                    "source": p.source,
                    "source_roadmap_id": p.source_roadmap_id,
                    "source_step_id": p.source_step_id,
                    "note_id": p.note_id,
                    "lean_compiled": p.lean_compiled,
                    "suspect": p.suspect,
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
                    "roadmap_id": r.roadmap_id,
                    "achieved": r.achieved,
                    "lesson": r.lesson,
                    "artifact_summaries": r.artifact_summaries,
                    "review_rejected": r.review_rejected,
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
                    "step_obligations": r.step_obligations,
                    "macro_steps": r.macro_steps,
                    "reasoning": r.reasoning,
                }
                for r in self.runner_up_roadmaps
            ],
            "handoff": asdict(self.handoff) if self.handoff else None,
        }
        # P3: Formal artifacts (omit when empty)
        if self.formal_artifacts:
            result["formal_artifacts"] = [
                {
                    "claim": a.claim,
                    "proof_text": a.proof_text,
                    "claim_status": a.claim_status,
                    "debt_label": a.debt_label,
                    "lean_statement": a.lean_statement,
                    "lean_sketch": a.lean_sketch,
                    "dependencies": a.dependencies,
                }
                for a in self.formal_artifacts
            ]
        # P4: Lemma queue (omit when empty)
        if self.lemma_queue:
            result["lemma_queue"] = [
                {
                    "lemma_type": lm.lemma_type,
                    "statement": lm.statement,
                    "source": lm.source,
                    "status": lm.status,
                    "unblocks": lm.unblocks,
                }
                for lm in self.lemma_queue
            ]
        # P7: Macro roadmap (omit when None)
        if self.macro_roadmap is not None:
            result["macro_roadmap"] = [
                {
                    "index": ms.index,
                    "description": ms.description,
                    "deliverable": ms.deliverable,
                    "sub_steps": [self._step_to_dict(s) for s in ms.sub_steps],
                    "status": ms.status,
                }
                for ms in self.macro_roadmap
            ]
        if self.knowledge_graph.nodes or self.knowledge_graph.edges:
            result["knowledge_graph"] = {
                "nodes": [
                    {
                        "node_id": node.node_id,
                        "node_type": node.node_type,
                        "statement": node.statement,
                        "status": node.status,
                        "source_attempt": node.source_attempt,
                        "source_step": node.source_step,
                        "evidence_summary": node.evidence_summary,
                        "reusable": node.reusable,
                        "stale": node.stale,
                        "alias_of": node.alias_of,
                    }
                    for node in self.knowledge_graph.nodes
                ],
                "edges": [
                    {
                        "source": edge.source,
                        "target": edge.target,
                        "edge_type": edge.edge_type,
                    }
                    for edge in self.knowledge_graph.edges
                ],
            }
        if self.failure_ledger:
            result["failure_ledger"] = [
                {
                    "key": entry.key,
                    "source_roadmap_id": entry.source_roadmap_id,
                    "count": entry.count,
                    "attempts": entry.attempts,
                    "first_attempt": entry.first_attempt,
                    "last_attempt": entry.last_attempt,
                    "diagnosis": entry.diagnosis,
                    "blocked_claim": entry.blocked_claim,
                    "motif": entry.motif,
                    "example_reason": entry.example_reason,
                    "do_not_retry_guidance": entry.do_not_retry_guidance,
                    "source_kind": entry.source_kind,
                    "linked_strategies": entry.linked_strategies,
                }
                for entry in self.failure_ledger
            ]
        if self.obligations:
            result["obligations"] = [
                {
                    "obligation_id": item.obligation_id,
                    "label": item.label,
                    "status": item.status,
                    "supporting_steps": item.supporting_steps,
                    "supporting_claim_ids": item.supporting_claim_ids,
                    "notes": item.notes,
                }
                for item in self.obligations
            ]
        if self.frontier is not None:
            result["frontier"] = {
                "roadmap_number": self.frontier.roadmap_number,
                "roadmap_id": self.frontier.roadmap_id,
                "active_step_index": self.frontier.active_step_index,
                "active_step_id": self.frontier.active_step_id,
                "active_step_label": self.frontier.active_step_label,
                "next_step_indices": self.frontier.next_step_indices,
                "current_blockers": self.frontier.current_blockers,
                "needed_proof_keys": self.frontier.needed_proof_keys,
                "open_obligations": self.frontier.open_obligations,
                "last_update_event": self.frontier.last_update_event,
            }
        if self.proof_index:
            result["proof_index"] = [
                {
                    "prop_id": item.prop_id,
                    "statement": item.statement,
                    "source": item.source,
                    "source_roadmap_id": item.source_roadmap_id,
                    "source_step_id": item.source_step_id,
                    "suspect": item.suspect,
                    "summary": item.summary,
                    "note_key": item.note_key,
                    "note_id": item.note_id,
                    "dependencies": item.dependencies,
                }
                for item in self.proof_index
            ]
        return result

    def to_json(self, indent: int = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @staticmethod
    def _step_from_dict(s: dict[str, Any]) -> RoadmapStep:
        """Deserialize a RoadmapStep from a dict."""
        return RoadmapStep(
            step_index=s["step_index"],
            description=s["description"],
            status=s["status"],
            roadmap_id=s.get("roadmap_id", ""),
            step_id=s.get("step_id", ""),
            result=s.get("result"),
            lean_status=s.get("lean_status"),
            # P6: checkpoint fields (optional, backward compat)
            claim=s.get("claim", ""),
            proof_text=s.get("proof_text", ""),
            verification_result=s.get("verification_result", ""),
            lemma_dependencies=s.get("lemma_dependencies", []),
            downstream_obligations=s.get("downstream_obligations", []),
            debt=s.get("debt", "none"),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoState:
        """Reconstruct from a plain dict (e.g. from ``json.loads``)."""
        current_roadmap = [
            cls._step_from_dict(s)
            for s in data.get("current_roadmap", [])
        ]

        proved_propositions = [
            ProvedProposition(
                prop_id=p["prop_id"],
                statement=p["statement"],
                source=p["source"],
                source_roadmap_id=p.get("source_roadmap_id", ""),
                source_step_id=p.get("source_step_id", ""),
                note_id=p.get("note_id", ""),
                lean_compiled=p.get("lean_compiled", False),
                suspect=p.get("suspect", False),
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
                roadmap_id=r.get("roadmap_id", ""),
                achieved=r.get("achieved", []),
                lesson=r.get("lesson", ""),
                artifact_summaries=r.get("artifact_summaries", []),
                review_rejected=r.get("review_rejected", False),
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
                step_obligations=r.get("step_obligations", []),
                macro_steps=r.get("macro_steps", []),
                reasoning=r.get("reasoning", ""),
            )
            for r in data.get("runner_up_roadmaps", [])
        ]

        handoff_raw = data.get("handoff")
        handoff = HandoffPacket(**handoff_raw) if handoff_raw else None

        # P3: Formal artifacts
        formal_artifacts = [
            FormalArtifact(
                claim=a.get("claim", ""),
                proof_text=a.get("proof_text", ""),
                claim_status=a.get("claim_status", "conjectured"),
                debt_label=a.get("debt_label", "none"),
                lean_statement=a.get("lean_statement", ""),
                lean_sketch=a.get("lean_sketch", ""),
                dependencies=a.get("dependencies", []),
            )
            for a in data.get("formal_artifacts", [])
        ]

        # P4: Lemma queue
        lemma_queue = [
            AuxiliaryLemma(
                lemma_type=lm.get("lemma_type", "sufficiency"),
                statement=lm.get("statement", ""),
                source=lm.get("source", ""),
                status=lm.get("status", "pending"),
                unblocks=lm.get("unblocks", []),
            )
            for lm in data.get("lemma_queue", [])
        ]

        # P7: Macro roadmap
        macro_raw = data.get("macro_roadmap")
        macro_roadmap = None
        if macro_raw is not None:
            macro_roadmap = [
                MacroStep(
                    index=ms["index"],
                    description=ms["description"],
                    deliverable=ms.get("deliverable", ""),
                    sub_steps=[cls._step_from_dict(s) for s in ms.get("sub_steps", [])],
                    status=ms.get("status", "UNPROVED"),
                )
                for ms in macro_raw
            ]

        graph_raw = data.get("knowledge_graph", {})
        knowledge_graph = KnowledgeGraph(
            nodes=[
                KGNode(
                    node_id=node["node_id"],
                    node_type=node["node_type"],
                    statement=node.get("statement", ""),
                    status=node.get("status", "proposed"),
                    source_attempt=int(node.get("source_attempt", 0)),
                    source_step=node.get("source_step"),
                    evidence_summary=node.get("evidence_summary", ""),
                    reusable=bool(node.get("reusable", False)),
                    source_roadmap_id=node.get("source_roadmap_id", ""),
                    source_step_id=node.get("source_step_id", ""),
                    stale=bool(node.get("stale", False)),
                    alias_of=node.get("alias_of"),
                )
                for node in graph_raw.get("nodes", [])
            ],
            edges=[
                KGEdge(
                    source=edge["source"],
                    target=edge["target"],
                    edge_type=edge["edge_type"],
                )
                for edge in graph_raw.get("edges", [])
            ],
        )
        failure_ledger = [
            FailureLedgerEntry(
                key=entry.get("key", ""),
                source_roadmap_id=entry.get("source_roadmap_id", ""),
                count=int(entry.get("count", 0)),
                attempts=[int(v) for v in entry.get("attempts", [])],
                first_attempt=int(entry.get("first_attempt", 0)),
                last_attempt=int(entry.get("last_attempt", 0)),
                diagnosis=entry.get("diagnosis", ""),
                blocked_claim=entry.get("blocked_claim", ""),
                motif=entry.get("motif", ""),
                example_reason=entry.get("example_reason", ""),
                do_not_retry_guidance=entry.get("do_not_retry_guidance", ""),
                source_kind=entry.get("source_kind", ""),
                linked_strategies=list(entry.get("linked_strategies", [])),
            )
            for entry in data.get("failure_ledger", [])
        ]
        obligations = [
            ObligationRecord(
                obligation_id=item.get("obligation_id", ""),
                label=item.get("label", ""),
                status=item.get("status", "open"),
                supporting_steps=[int(v) for v in item.get("supporting_steps", [])],
                supporting_claim_ids=list(item.get("supporting_claim_ids", [])),
                notes=item.get("notes", ""),
            )
            for item in data.get("obligations", [])
        ]
        frontier_raw = data.get("frontier")
        frontier = FrontierState(
            roadmap_number=int(frontier_raw.get("roadmap_number", 0)),
            roadmap_id=frontier_raw.get("roadmap_id", ""),
            active_step_index=int(frontier_raw.get("active_step_index", 0)),
            active_step_id=frontier_raw.get("active_step_id", ""),
            active_step_label=frontier_raw.get("active_step_label", ""),
            next_step_indices=[int(v) for v in frontier_raw.get("next_step_indices", [])],
            current_blockers=list(frontier_raw.get("current_blockers", [])),
            needed_proof_keys=list(frontier_raw.get("needed_proof_keys", [])),
            open_obligations=list(frontier_raw.get("open_obligations", [])),
            last_update_event=frontier_raw.get("last_update_event", ""),
        ) if frontier_raw else None
        proof_index = [
            ProofIndexEntry(
                prop_id=item.get("prop_id", ""),
                statement=item.get("statement", ""),
                source=item.get("source", ""),
                source_roadmap_id=item.get("source_roadmap_id", ""),
                source_step_id=item.get("source_step_id", ""),
                suspect=bool(item.get("suspect", False)),
                summary=item.get("summary", ""),
                note_key=item.get("note_key", item.get("prop_id", "")),
                note_id=item.get("note_id", ""),
                dependencies=list(item.get("dependencies", [])),
            )
            for item in data.get("proof_index", [])
        ]

        return cls(
            current_roadmap_id=data.get("current_roadmap_id", ""),
            current_approach=data.get("current_approach", ""),
            current_roadmap=current_roadmap,
            proved_propositions=proved_propositions,
            refuted_propositions=refuted_propositions,
            previous_roadmaps=previous_roadmaps,
            runner_up_roadmaps=runner_up_roadmaps,
            handoff=handoff,
            formal_artifacts=formal_artifacts,
            lemma_queue=lemma_queue,
            macro_roadmap=macro_roadmap,
            knowledge_graph=knowledge_graph,
            failure_ledger=failure_ledger,
            obligations=obligations,
            frontier=frontier,
            proof_index=proof_index,
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

    @staticmethod
    def _failure_guidance(diagnosis: str, blocked_claim: str, motif: str) -> str:
        if diagnosis == "FALSE_PROPOSITION":
            return f"Do not retry this false claim: {blocked_claim or motif}"
        if diagnosis == "INSUFFICIENT_TECHNIQUE":
            return (
                "Do not reuse this structure unless a genuinely new lemma "
                "or technique is introduced."
            )
        if diagnosis == "LOGICAL_GAP":
            return (
                "Do not reuse this step pattern unless the missing bridge "
                "is supplied explicitly."
            )
        if diagnosis == "REVIEW_GAP":
            return "Do not cite this roadmap's claims until the review gap is repaired."
        if diagnosis == "FALSIFIER_REJECTION":
            return "Do not reuse this proof shape without addressing the falsifier finding."
        if diagnosis == "STAGNATION":
            return "Avoid this roadmap unless the blocked motif is changed materially."
        return "Treat this pattern as suspect until new evidence appears."

    def _upsert_failure_ledger_entry(
        self,
        state: MemoState,
        *,
        attempt: int,
        source_roadmap_id: str,
        diagnosis: str,
        blocked_claim: str,
        motif: str,
        example_reason: str,
        source_kind: str,
        strategy_ref: str = "",
    ) -> None:
        normalized_claim = _normalize_failure_text(blocked_claim, limit=90)
        normalized_motif = _normalize_failure_text(motif or example_reason, limit=120)
        key = f"{diagnosis}|{normalized_claim}|{normalized_motif}"
        for entry in state.failure_ledger:
            if entry.key != key:
                continue
            entry.count += 1
            if attempt not in entry.attempts:
                entry.attempts.append(attempt)
            entry.last_attempt = max(entry.last_attempt, attempt)
            if example_reason and len(example_reason) >= len(entry.example_reason):
                entry.example_reason = example_reason[:320]
            if strategy_ref and strategy_ref not in entry.linked_strategies:
                entry.linked_strategies.append(strategy_ref)
            return

        state.failure_ledger.append(
            FailureLedgerEntry(
                key=key,
                source_roadmap_id=source_roadmap_id,
                count=1,
                attempts=[attempt] if attempt else [],
                first_attempt=attempt,
                last_attempt=attempt,
                diagnosis=diagnosis,
                blocked_claim=blocked_claim[:200],
                motif=(motif or example_reason)[:200],
                example_reason=example_reason[:320],
                do_not_retry_guidance=self._failure_guidance(
                    diagnosis, blocked_claim, motif or example_reason
                ),
                source_kind=source_kind,
                linked_strategies=[strategy_ref] if strategy_ref else [],
            )
        )

    def _sorted_failure_ledger(self, state: MemoState) -> list[FailureLedgerEntry]:
        return sorted(
            state.failure_ledger,
            key=lambda entry: (
                entry.count,
                int(entry.diagnosis in {"FALSE_PROPOSITION", "FALSIFIER_REJECTION"}),
                entry.last_attempt,
            ),
            reverse=True,
        )

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

    @staticmethod
    def _obligation_descriptions() -> dict[str, str]:
        return {
            "necessary_direction": "Derive the necessary direction / constraints from the hypothesis.",
            "sufficiency_direction": "Prove the sufficiency or converse direction.",
            "existence_or_construction": "Construct or exhibit the required object and verify it works.",
            "boundary_or_small_cases": "Handle the boundary, degenerate, or small cases explicitly.",
            "final_target_link": "Combine intermediate claims into the exact original theorem.",
        }

    @classmethod
    def _normalize_obligation_id(cls, raw: str) -> str:
        head = (raw or "").strip().lower()
        if ":" in head:
            head = head.split(":", 1)[0].strip()
        aliases = {
            "necessary": "necessary_direction",
            "necessary_direction": "necessary_direction",
            "sufficiency": "sufficiency_direction",
            "sufficient": "sufficiency_direction",
            "sufficiency_direction": "sufficiency_direction",
            "converse": "sufficiency_direction",
            "existence": "existence_or_construction",
            "construction": "existence_or_construction",
            "existence_or_construction": "existence_or_construction",
            "boundary": "boundary_or_small_cases",
            "boundary_or_small_cases": "boundary_or_small_cases",
            "small_cases": "boundary_or_small_cases",
            "final_target_link": "final_target_link",
            "final": "final_target_link",
            "final_synthesis": "final_target_link",
        }
        return aliases.get(head, head)

    @classmethod
    def _infer_obligations_from_text(cls, text: str) -> list[str]:
        lowered = " ".join((text or "").lower().split())
        hits: list[str] = []

        def add(key: str) -> None:
            normalized = cls._normalize_obligation_id(key)
            if normalized and normalized not in hits:
                hits.append(normalized)

        if any(token in lowered for token in ("necessary", "only if", "constraint", "derive necessary", "must satisfy")):
            add("necessary_direction")
        if any(
            token in lowered
            for token in (
                "sufficiency",
                "sufficient",
                "converse",
                "for sufficiency",
                "verify each candidate",
                "verify the candidate",
                "show the candidate works",
                "show each candidate works",
                "if direction",
            )
        ):
            add("sufficiency_direction")
        if any(
            token in lowered
            for token in (
                "construct",
                "build",
                "define",
                "choose",
                "exhibit",
                "produce",
                "there exists",
                "realize",
            )
        ):
            add("existence_or_construction")
        if any(
            token in lowered
            for token in (
                "boundary",
                "small case",
                "small cases",
                "base case",
                "degenerate",
                "edge case",
                "check n=",
                "check p=",
                "comput",
            )
        ):
            add("boundary_or_small_cases")
        if any(
            token in lowered
            for token in (
                "conclude",
                "therefore",
                "hence",
                "finish",
                "complete the proof",
                "deduce the theorem",
                "combine the previous",
                "establish the theorem",
                "show the iff",
            )
        ):
            add("final_target_link")
        if "existence_or_construction" in hits and any(
            token in lowered for token in ("verify", "satisfies", "works", "sigma-good")
        ):
            add("sufficiency_direction")
        return hits

    def _derive_obligations(self, state: MemoState) -> list[ObligationRecord]:
        if not state.current_roadmap:
            return []

        descriptions = self._obligation_descriptions()
        records: dict[str, ObligationRecord] = {}
        step_map = {step.step_index: step for step in state.current_roadmap}

        for step in state.current_roadmap:
            obligations = step.downstream_obligations or self._infer_obligations_from_text(
                step.description
            )
            for raw in obligations:
                obligation_id = self._normalize_obligation_id(raw)
                if not obligation_id:
                    continue
                record = records.setdefault(
                    obligation_id,
                    ObligationRecord(
                        obligation_id=obligation_id,
                        label=descriptions.get(obligation_id, obligation_id.replace("_", " ")),
                    ),
                )
                if step.status == "PROVED":
                    record.status = "covered"
                    if step.step_index not in record.supporting_steps:
                        record.supporting_steps.append(step.step_index)

        for prop in state.proved_propositions:
            step = None
            if prop.source_step_id:
                step = next(
                    (
                        candidate
                        for candidate in state.current_roadmap
                        if candidate.step_id == prop.source_step_id
                    ),
                    None,
                )
            if step is None:
                _, step_index = self._roadmap_attempt_from_source(prop.source)
                if step_index is None:
                    continue
                step = step_map.get(step_index)
            if step is None:
                continue
            obligations = step.downstream_obligations or self._infer_obligations_from_text(
                step.description
            )
            for raw in obligations:
                obligation_id = self._normalize_obligation_id(raw)
                if not obligation_id:
                    continue
                record = records.setdefault(
                    obligation_id,
                    ObligationRecord(
                        obligation_id=obligation_id,
                        label=descriptions.get(obligation_id, obligation_id.replace("_", " ")),
                    ),
                )
                if prop.prop_id not in record.supporting_claim_ids:
                    record.supporting_claim_ids.append(prop.prop_id)

        return sorted(records.values(), key=lambda item: item.obligation_id)

    def _derive_proof_index(self, state: MemoState) -> list[ProofIndexEntry]:
        edges_by_source: dict[str, list[str]] = {}
        for edge in state.knowledge_graph.edges:
            if edge.edge_type != "depends_on":
                continue
            if not edge.source.startswith("claim_"):
                continue
            if not edge.target.startswith("claim_"):
                continue
            edges_by_source.setdefault(edge.source, []).append(
                edge.target.removeprefix("claim_")
            )

        entries: list[ProofIndexEntry] = []
        for prop in state.proved_propositions:
            summary = " ".join(prop.statement.split())
            if len(summary) > 180:
                summary = summary[:177].rstrip() + "..."
            entries.append(
                ProofIndexEntry(
                    prop_id=prop.prop_id,
                    statement=prop.statement,
                    source=prop.source,
                    source_roadmap_id=prop.source_roadmap_id,
                    source_step_id=prop.source_step_id,
                    suspect=prop.suspect,
                    summary=summary,
                    note_key=prop.prop_id,
                    note_id=prop.note_id,
                    dependencies=sorted(
                        set(edges_by_source.get(f"claim_{prop.prop_id}", []))
                    ),
                )
            )
        entries.sort(key=lambda item: (item.suspect, item.prop_id))
        return entries

    def _derive_frontier(self, state: MemoState) -> FrontierState | None:
        if not state.current_roadmap:
            return None

        active_step = next(
            (
                step
                for step in state.current_roadmap
                if step.status in {"UNPROVED", "IN_PROGRESS"}
            ),
            None,
        )
        remaining = [
            step.step_index
            for step in state.current_roadmap
            if step.status in {"UNPROVED", "IN_PROGRESS"}
        ]
        failed = [
            step
            for step in state.current_roadmap
            if step.status == "FAILED"
        ]
        blockers: list[str] = []
        for step in failed[:3]:
            detail = (step.result or "").strip()
            blockers.append(
                f"Step {step.step_index}: {step.description}"
                + (f" -- {detail[:120]}" if detail else "")
            )
        for entry in self._sorted_failure_ledger(state):
            label = (entry.blocked_claim or entry.motif or "").strip()
            if not label:
                continue
            candidate = f"[{entry.diagnosis}] {label}"
            if candidate not in blockers:
                blockers.append(candidate)
            if len(blockers) >= 6:
                break

        if active_step is not None:
            needed_proof_keys = state.knowledge_graph.select_relevant_claim_keys(
                active_step.description,
                max_items=4,
            )
            active_step_label = f"Step {active_step.step_index}: {active_step.description}"
        else:
            needed_proof_keys = []
            active_step_label = ""

        return FrontierState(
            roadmap_number=len(state.previous_roadmaps) + (1 if state.current_roadmap else 0),
            roadmap_id=state.current_roadmap_id,
            active_step_index=active_step.step_index if active_step is not None else 0,
            active_step_id=active_step.step_id if active_step is not None else "",
            active_step_label=active_step_label,
            next_step_indices=remaining[:3],
            current_blockers=blockers,
            needed_proof_keys=needed_proof_keys,
            open_obligations=[
                item.obligation_id for item in state.obligations if item.status != "covered"
            ],
            last_update_event=(state.frontier.last_update_event if state.frontier else ""),
        )

    def _synchronize_structured_state(self, state: MemoState) -> MemoState:
        if state.current_roadmap and not state.current_roadmap_id:
            state.current_roadmap_id = "legacy-current-roadmap"
        for step in state.current_roadmap:
            if not step.roadmap_id:
                step.roadmap_id = state.current_roadmap_id
            if not step.step_id:
                step.step_id = f"{step.roadmap_id}:step:{step.step_index}"
        state.obligations = self._derive_obligations(state)
        state.proof_index = self._derive_proof_index(state)
        state.frontier = self._derive_frontier(state)
        return state

    def save(self, state: MemoState) -> None:
        """Write both ``MEMO.json`` (canonical) and ``MEMO.md`` (render)."""
        state = self._synchronize_structured_state(state)
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        self.json_path.write_text(state.to_json(), encoding="utf-8")
        self.md_path.write_text(self._render_md(state), encoding="utf-8")

    # ------------------------------------------------------------------
    # Incremental Updates
    # ------------------------------------------------------------------

    @staticmethod
    def _roadmap_attempt_from_source(source: str) -> tuple[int, int | None]:
        roadmap_name, step_index = _parse_prop_source(source)
        if roadmap_name is None or not roadmap_name.startswith("Roadmap "):
            return 0, step_index
        suffix = roadmap_name.removeprefix("Roadmap ").strip()
        return (int(suffix) if suffix.isdigit() else 0), step_index

    @staticmethod
    def _roadmap_attempt_from_name(name: str) -> int:
        match = re.search(r"Roadmap\s+(\d+)", name)
        return int(match.group(1)) if match else 0

    def _graph_record_strategy(
        self,
        state: MemoState,
        *,
        roadmap_name: str,
        roadmap_id: str,
        approach: str,
        steps: list[RoadmapStep],
    ) -> str:
        attempt = self._roadmap_attempt_from_name(roadmap_name)
        node_id = f"strategy_{roadmap_id or attempt or len(state.previous_roadmaps) + 1}"
        preview = "; ".join(step.description for step in steps[:4])
        state.knowledge_graph.upsert_node(
            KGNode(
                node_id=node_id,
                node_type="strategy",
                statement=approach or roadmap_name,
                status="proposed",
                source_attempt=attempt,
                source_step=None,
                evidence_summary=preview[:320],
                reusable=True,
                source_roadmap_id=roadmap_id,
            )
        )
        state.knowledge_graph.enforce_active_cap()
        return node_id

    def record_generated_strategy(
        self,
        roadmap_name: str,
        approach: str,
        steps: list[RoadmapStep],
        roadmap_id: str = "",
    ) -> None:
        state = self.load()
        self._graph_record_strategy(
            state,
            roadmap_name=roadmap_name,
            roadmap_id=roadmap_id,
            approach=approach,
            steps=steps,
        )
        self.save(state)

    @staticmethod
    def _strategy_node_for(
        state: MemoState,
        *,
        roadmap_number: int,
        roadmap_id: str | None = None,
    ) -> KGNode | None:
        for node in state.knowledge_graph.nodes:
            if node.node_type != "strategy":
                continue
            if roadmap_id and node.source_roadmap_id == roadmap_id:
                return node
            if node.node_id == f"strategy_{roadmap_number}":
                return node
        return None

    def _graph_mark_claim_status(
        self,
        state: MemoState,
        attempt: int,
        status: str,
        *,
        roadmap_id: str | None = None,
    ) -> None:
        for node in state.knowledge_graph.nodes:
            if node.node_type != "claim":
                continue
            if roadmap_id:
                if node.source_roadmap_id != roadmap_id:
                    continue
            elif node.source_attempt != attempt:
                continue
            if KG_STATUS_RANK[status] >= KG_STATUS_RANK.get(node.status, 0):
                node.status = status
        state.knowledge_graph.enforce_active_cap()

    def set_current_roadmap(
        self,
        steps: list[RoadmapStep],
        *,
        roadmap_id: str | None = None,
        approach: str | None = None,
    ) -> None:
        """Set a flat current roadmap and clear any stale macro view."""
        state = self.load()
        if roadmap_id is not None:
            state.current_roadmap_id = roadmap_id
        if approach is not None:
            state.current_approach = approach
        for step in steps:
            if state.current_roadmap_id and not step.roadmap_id:
                step.roadmap_id = state.current_roadmap_id
            if not step.step_id:
                base = step.roadmap_id or state.current_roadmap_id or "current-roadmap"
                step.step_id = f"{base}:step:{step.step_index}"
        state.current_roadmap = steps
        state.macro_roadmap = None
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
        if state.macro_roadmap:
            for macro in state.macro_roadmap:
                for sub_step in macro.sub_steps:
                    if sub_step.step_index == step_index:
                        sub_step.status = status
                        sub_step.result = brief_result
                macro.update_status()
        self.save(state)

    def add_proved_proposition(
        self,
        prop_id: str,
        statement: str,
        source: str,
        *,
        source_roadmap_id: str = "",
        source_step_id: str = "",
        note_id: str = "",
    ) -> None:
        """Add a proved proposition to the MEMO."""
        state = self.load()
        # Avoid duplicates
        existing_ids = {p.prop_id for p in state.proved_propositions}
        if prop_id not in existing_ids:
            state.proved_propositions.append(
                ProvedProposition(
                    prop_id,
                    statement,
                    source,
                    source_roadmap_id=source_roadmap_id,
                    source_step_id=source_step_id,
                    note_id=note_id,
                )
            )
        else:
            for proposition in state.proved_propositions:
                if proposition.prop_id != prop_id:
                    continue
                if source_roadmap_id and not proposition.source_roadmap_id:
                    proposition.source_roadmap_id = source_roadmap_id
                if source_step_id and not proposition.source_step_id:
                    proposition.source_step_id = source_step_id
                if note_id and not proposition.note_id:
                    proposition.note_id = note_id
                break
        attempt, step_index = self._roadmap_attempt_from_source(source)
        graph = state.knowledge_graph
        graph.upsert_node(
            KGNode(
                node_id=f"claim_{prop_id}",
                node_type="claim",
                statement=statement,
                status="argued",
                source_attempt=attempt,
                source_step=step_index,
                evidence_summary=f"{prop_id} recorded from {source}",
                reusable=True,
                source_roadmap_id=source_roadmap_id,
                source_step_id=source_step_id,
            )
        )
        normalized = " ".join(statement.lower().split())
        for node in graph.nodes:
            if node.node_type != "claim" or node.node_id == f"claim_{prop_id}":
                continue
            if " ".join(node.statement.lower().split()) == normalized:
                node.status = "cross_attempt_reused"
                current = graph.get_node(f"claim_{prop_id}")
                if current is not None:
                    current.status = "cross_attempt_reused"
                    graph.add_edge(KGEdge(source=current.node_id, target=node.node_id, edge_type="variant_of"))
                    graph.add_edge(KGEdge(source=node.node_id, target=current.node_id, edge_type="variant_of"))
        graph.enforce_active_cap()
        self.save(state)

    def archive_roadmap(
        self,
        roadmap_name: str,
        approach: str,
        failure_reason: str,
        achieved: list[str],
        lesson: str,
        failed_steps: list[StepFailure] | None = None,
        review_rejected: bool = False,
        roadmap_id: str = "",
    ) -> None:
        """Move the current roadmap to Previous Roadmaps and clear it.

        When *review_rejected* is True, every proposition whose ``source``
        names this roadmap is flagged ``suspect=True``. This prevents the
        next roadmap's planner from treating review-rejected lemmas as
        trustworthy prior results. The source format written by
        ``Phase1Runner`` is fixed as ``"Roadmap {n}, step {k}"``, so we
        match on the prefix ``"{roadmap_name}, step "``.
        """
        state = self.load()
        active_roadmap_id = roadmap_id or state.current_roadmap_id
        roadmap_claims = {
            step.claim or step.description
            for step in state.current_roadmap
            if step.claim or step.description
        }
        artifact_summaries = []
        for art in state.formal_artifacts:
            if art.claim in roadmap_claims:
                debt_tag = (
                    f" [DEBT: {art.debt_label}]"
                    if art.debt_label != "none"
                    else ""
                )
                artifact_summaries.append(
                    f"{art.claim[:80]} [{art.claim_status}]{debt_tag}"
                )
        if review_rejected:
            prefix = f"{roadmap_name}, step "
            for prop in state.proved_propositions:
                if active_roadmap_id and prop.source_roadmap_id == active_roadmap_id:
                    prop.suspect = True
                elif prop.source.startswith(prefix):
                    prop.suspect = True
        attempt = self._roadmap_attempt_from_name(roadmap_name)
        strategy_node_id = self._graph_record_strategy(
            state,
            roadmap_name=roadmap_name,
            roadmap_id=active_roadmap_id,
            approach=approach,
            steps=state.current_roadmap,
        )
        if review_rejected:
            self._graph_mark_claim_status(state, attempt, "suspect")
        state.previous_roadmaps.append(
            ArchivedRoadmap(
                name=roadmap_name,
                approach=approach,
                failure_reason=failure_reason,
                roadmap_id=active_roadmap_id,
                achieved=achieved,
                lesson=lesson,
                failed_steps=failed_steps or [],
                artifact_summaries=artifact_summaries,
                review_rejected=review_rejected,
            )
        )
        obstruction_nodes: list[str] = []
        if failed_steps:
            for failure in failed_steps:
                obstruction_id = f"obstruction_{attempt}_{failure.step_index}_{len(state.previous_roadmaps)}"
                self._upsert_failure_ledger_entry(
                    state,
                    attempt=attempt,
                    source_roadmap_id=state.current_roadmap_id or roadmap_name,
                    diagnosis=failure.diagnosis,
                    blocked_claim=failure.false_claim or failure.description,
                    motif=failure.explanation,
                    example_reason=failure.explanation,
                    source_kind="failed_step",
                    strategy_ref=roadmap_name,
                )
                state.knowledge_graph.upsert_node(
                    KGNode(
                        node_id=obstruction_id,
                        node_type="obstruction",
                        statement=failure.false_claim or failure.description,
                        status="refuted" if failure.diagnosis == "FALSE_PROPOSITION" else "suspect",
                        source_attempt=attempt,
                        source_step=failure.step_index,
                        evidence_summary=failure.explanation[:320],
                        reusable=False,
                    )
                )
                state.knowledge_graph.add_edge(
                    KGEdge(source=obstruction_id, target=strategy_node_id, edge_type="refutes")
                )
                obstruction_nodes.append(obstruction_id)
        elif failure_reason:
            self._upsert_failure_ledger_entry(
                state,
                attempt=attempt,
                source_roadmap_id=state.current_roadmap_id or roadmap_name,
                diagnosis="ROADMAP_FAILURE",
                blocked_claim=approach or roadmap_name,
                motif=failure_reason,
                example_reason=lesson or failure_reason,
                source_kind="roadmap_failure",
                strategy_ref=roadmap_name,
            )
            obstruction_id = f"obstruction_{attempt}_{len(state.previous_roadmaps)}"
            state.knowledge_graph.upsert_node(
                KGNode(
                    node_id=obstruction_id,
                    node_type="obstruction",
                    statement=failure_reason[:200],
                    status="suspect",
                    source_attempt=attempt,
                    source_step=None,
                    evidence_summary=lesson[:320] or failure_reason[:320],
                    reusable=False,
                )
            )
            state.knowledge_graph.add_edge(
                KGEdge(source=obstruction_id, target=strategy_node_id, edge_type="refutes")
            )
        state.current_roadmap = []
        state.current_roadmap_id = ""
        state.current_approach = ""
        state.macro_roadmap = None
        state.knowledge_graph.enforce_active_cap()
        self.save(state)

    def quarantine_cross_session_propositions(self) -> int:
        """Mark stale cross-session propositions as suspect.

        Fix 4: the in-session ``archive_roadmap(review_rejected=True)`` path
        only scrubs propositions whose source names the roadmap being
        archived *in the current session*. When a session resumes from a
        MEMO.json written by a prior run, the ``ProvedProposition`` entries
        from that prior run have sources like ``"Roadmap 3, step 2"`` that
        the new session's roadmap counter never matches — so a proposition
        the reviewer already rejected last time sits in the "trusted"
        bucket and can be cited as a premise by the next planner.

        This helper walks the persisted MEMO and flags as suspect every
        proposition whose origin roadmap is either:
          1. Already present in ``previous_roadmaps`` with
             ``review_rejected=True`` (or matches the legacy string
             heuristic), OR
          2. An "orphan" — the source references a roadmap name that is
             NOT in ``previous_roadmaps`` AND the step index does not
             correspond to any PROVED step in the current in-progress
             roadmap. These are propositions whose provenance the current
             MEMO cannot verify, so they must not be trusted as premises.

        Already-suspect propositions are left untouched. In-progress
        propositions whose step index matches a PROVED step in
        ``current_roadmap`` are preserved (they belong to the roadmap the
        resume branch is about to verify, and that verification is a
        stronger signal than any heuristic here).

        Returns the number of propositions that were newly flagged. A
        return value of 0 means either there was nothing to quarantine or
        every suspicious proposition was already flagged.
        """
        state = self.load()
        if not state.proved_propositions:
            return 0

        rejected_archive_names: set[str] = set()
        rejected_archive_ids: set[str] = set()
        known_archive_names: set[str] = set()
        known_archive_ids: set[str] = set()
        for archive in state.previous_roadmaps:
            known_archive_names.add(archive.name)
            if archive.roadmap_id:
                known_archive_ids.add(archive.roadmap_id)
            if _is_review_rejected(archive):
                rejected_archive_names.add(archive.name)
                if archive.roadmap_id:
                    rejected_archive_ids.add(archive.roadmap_id)

        # In-progress propositions we must NOT touch: any prop whose step
        # index matches a PROVED step in the current roadmap. The resume
        # branch will re-verify that roadmap separately.
        in_progress_proved_step_indices = {
            step.step_index
            for step in state.current_roadmap
            if step.status == "PROVED"
        }
        in_progress_step_ids = {
            step.step_id
            for step in state.current_roadmap
            if step.status == "PROVED" and step.step_id
        }

        newly_suspect = 0
        for prop in state.proved_propositions:
            if prop.suspect:
                continue
            roadmap_name, step_index = _parse_prop_source(prop.source)

            if prop.source_roadmap_id and prop.source_roadmap_id in rejected_archive_ids:
                prop.suspect = True
                newly_suspect += 1
                continue

            # Case 1: explicit review-rejected archive match.
            if roadmap_name is not None and roadmap_name in rejected_archive_names:
                prop.suspect = True
                newly_suspect += 1
                continue

            # Case 2: orphan — unrecognised source.
            # Skip lemma-queue props (they have no roadmap name to match
            # against) unless the step index is also an orphan. Skip
            # in-progress proved-step propositions because the resume
            # branch owns their verification.
            if roadmap_name is None:
                # Unparseable source — leave it alone; too risky to guess.
                continue
            if roadmap_name == "Lemma queue":
                # Lemma-queue sources predate the current session only
                # when there is no current roadmap at all. In a resumed
                # run with an in-progress roadmap, lemma-queue props are
                # owned by the resume path.
                if not state.current_roadmap:
                    prop.suspect = True
                    newly_suspect += 1
                continue
            # Normal "Roadmap N, step K" orphan — the roadmap name is
            # not in previous_roadmaps AND step K is not an in-progress
            # PROVED step. Flag it.
            if (
                (prop.source_roadmap_id and prop.source_roadmap_id not in known_archive_ids)
                or (not prop.source_roadmap_id and roadmap_name not in known_archive_names)
            ):
                if (
                    (prop.source_step_id and prop.source_step_id not in in_progress_step_ids)
                    or (
                        not prop.source_step_id
                        and (step_index is None or step_index not in in_progress_proved_step_indices)
                    )
                ):
                    prop.suspect = True
                    newly_suspect += 1

        if newly_suspect:
            self.save(state)
        return newly_suspect

    # ------------------------------------------------------------------
    # Pre-roadmap deduplication
    # ------------------------------------------------------------------

    @staticmethod
    def _source_rank(source: str) -> int:
        """Extract roadmap number from a source string for ordering.

        ``"Roadmap 3, step 5"`` → ``3``.  Falls back to ``0`` for
        unrecognisable formats (e.g. ``"Lemma queue, step 2"``).
        """
        import re as _re

        m = _re.match(r"Roadmap\s+(\d+)", source)
        return int(m.group(1)) if m else 0

    def deduplicate_propositions(self) -> list[str]:
        """Remove duplicate propositions, keeping the best of each.

        Groups propositions by **normalised statement text** (lowercase,
        whitespace-collapsed).  Within each group of size > 1, keeps the
        single best entry and removes the rest.

        Scoring (higher wins, evaluated left-to-right):
          1. non-suspect beats suspect,
          2. lean_compiled beats not compiled,
          3. higher roadmap number beats lower.

        Returns the ``prop_id`` list of removed entries (may be empty).
        """
        state = self.load()
        if not state.proved_propositions:
            return []

        # Group by normalised statement
        groups: dict[str, list[ProvedProposition]] = {}
        for prop in state.proved_propositions:
            key = " ".join(prop.statement.lower().split())
            groups.setdefault(key, []).append(prop)

        removed_ids: list[str] = []
        kept: list[ProvedProposition] = []

        for group in groups.values():
            if len(group) == 1:
                kept.append(group[0])
                continue
            # Sort best-first
            group.sort(
                key=lambda p: (
                    not p.suspect,            # False < True → non-suspect first
                    p.lean_compiled,           # True > False → compiled first
                    self._source_rank(p.source),
                ),
                reverse=True,
            )
            kept.append(group[0])
            for dup in group[1:]:
                removed_ids.append(dup.prop_id)

        if not removed_ids:
            return []

        state.proved_propositions = kept
        self.save(state)
        return removed_ids

    def prior_attempts_summary(self) -> list[dict[str, str]]:
        """Summarise abandoned roadmaps for the planner (Fix 5).

        Returns a list of ``{approach, failure_reason, lesson,
        review_rejected}`` dicts, one per archived roadmap. This lets the
        planner-side prompt code decide whether to inject a strategic
        divergence instruction without re-parsing the MEMO.md text.
        """
        state = self.load()
        return [
            {
                "name": archive.name,
                "approach": archive.approach,
                "failure_reason": archive.failure_reason,
                "lesson": archive.lesson,
                "review_rejected": "true" if _is_review_rejected(archive) else "false",
            }
            for archive in state.previous_roadmaps
        ]

    def add_refuted_proposition(self, failure: StepFailure) -> None:
        """Record a refuted proposition so future roadmaps avoid it."""
        state = self.load()
        # Avoid duplicates by checking false_claim
        existing = {rp.false_claim for rp in state.refuted_propositions if rp.false_claim}
        if failure.false_claim and failure.false_claim not in existing:
            state.refuted_propositions.append(failure)
            claim_id = f"refuted_claim_{len(state.refuted_propositions)}"
            obstruction_id = f"obstruction_refuted_{len(state.refuted_propositions)}"
            state.knowledge_graph.upsert_node(
                KGNode(
                    node_id=claim_id,
                    node_type="claim",
                    statement=failure.false_claim or failure.description,
                    status="refuted",
                    source_attempt=0,
                    source_step=failure.step_index,
                    evidence_summary=failure.explanation[:320],
                    reusable=False,
                )
            )
            state.knowledge_graph.upsert_node(
                KGNode(
                    node_id=obstruction_id,
                    node_type="obstruction",
                    statement=failure.explanation[:200],
                    status="refuted",
                    source_attempt=0,
                    source_step=failure.step_index,
                    evidence_summary=failure.explanation[:320],
                    reusable=False,
                )
            )
            state.knowledge_graph.add_edge(
                KGEdge(source=obstruction_id, target=claim_id, edge_type="refutes")
            )
            state.knowledge_graph.enforce_active_cap()
            self.save(state)

    def mark_review_outcome(
        self,
        roadmap_number: int,
        *,
        roadmap_id: str | None = None,
        accepted: bool,
        gaps: list[str] | None = None,
    ) -> None:
        state = self.load()
        status = "review_supported" if accepted else "suspect"
        self._graph_mark_claim_status(state, roadmap_number, status, roadmap_id=roadmap_id)
        strategy = self._strategy_node_for(
            state,
            roadmap_number=roadmap_number,
            roadmap_id=roadmap_id,
        )
        if strategy is not None and accepted:
            strategy.status = "review_supported"
        elif strategy is not None and not accepted:
            strategy.status = "suspect"
        if not accepted and gaps:
            for gap in gaps:
                self._upsert_failure_ledger_entry(
                    state,
                    attempt=roadmap_number,
                    source_roadmap_id=roadmap_id or f"Roadmap {roadmap_number}",
                    diagnosis="REVIEW_GAP",
                    blocked_claim=f"Roadmap {roadmap_number}",
                    motif=gap,
                    example_reason=gap,
                    source_kind="review_gap",
                    strategy_ref=f"Roadmap {roadmap_number}",
                )
            obstruction_id = f"obstruction_review_{roadmap_number}_{len(gaps)}"
            state.knowledge_graph.upsert_node(
                KGNode(
                    node_id=obstruction_id,
                    node_type="obstruction",
                    statement="; ".join(gaps)[:200],
                    status="suspect",
                    source_attempt=roadmap_number,
                    source_step=None,
                    evidence_summary="; ".join(gaps)[:320],
                    reusable=False,
                )
            )
            if strategy is not None:
                state.knowledge_graph.add_edge(
                    KGEdge(source=obstruction_id, target=strategy.node_id, edge_type="refutes")
                )
        state.knowledge_graph.enforce_active_cap()
        self.save(state)

    def record_falsifier_failure(
        self,
        roadmap_number: int,
        *,
        roadmap_id: str | None = None,
        feedback: str,
    ) -> None:
        state = self.load()
        self._upsert_failure_ledger_entry(
            state,
            attempt=roadmap_number,
            source_roadmap_id=roadmap_id or f"Roadmap {roadmap_number}",
            diagnosis="FALSIFIER_REJECTION",
            blocked_claim=f"Roadmap {roadmap_number}",
            motif=feedback,
            example_reason=feedback,
            source_kind="falsifier",
            strategy_ref=f"Roadmap {roadmap_number}",
        )
        self.save(state)

    def record_stagnation(
        self,
        roadmap_number: int,
        *,
        roadmap_id: str | None = None,
        summary: str,
    ) -> None:
        state = self.load()
        self._upsert_failure_ledger_entry(
            state,
            attempt=roadmap_number,
            source_roadmap_id=roadmap_id or f"Roadmap {roadmap_number}",
            diagnosis="STAGNATION",
            blocked_claim=f"Roadmap {roadmap_number}",
            motif=summary,
            example_reason=summary,
            source_kind="stagnation",
            strategy_ref=f"Roadmap {roadmap_number}",
        )
        self.save(state)

    def store_runner_ups(self, roadmaps: list[dict]) -> None:
        """Store runner-up roadmaps (the ones not chosen on first attempt)."""
        state = self.load()
        state.runner_up_roadmaps = [
            RunnerUpRoadmap(
                approach=r.get("approach", ""),
                steps=r.get("steps", []),
                step_obligations=r.get("step_obligations", []),
                macro_steps=r.get("macro_steps", []),
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

    # --- P4: Lemma queue operations ---

    def enqueue_lemma(self, lemma: AuxiliaryLemma) -> None:
        """Add an auxiliary lemma to the queue."""
        state = self.load()
        state.lemma_queue.append(lemma)
        self.save(state)

    def resolve_lemma(self, index: int) -> None:
        """Mark a lemma in the queue as resolved."""
        state = self.load()
        if 0 <= index < len(state.lemma_queue):
            state.lemma_queue[index].status = "resolved"
            self.save(state)

    # --- P3: Formal artifact operations ---

    def upsert_formal_artifact(
        self,
        *,
        claim: str,
        proof_text: str = "",
        claim_status: str = "conjectured",
        debt_label: str = "none",
        lean_statement: str = "",
        lean_sketch: str = "",
        dependencies: list[str] | None = None,
    ) -> None:
        """Insert or update a formal artifact keyed by its claim text."""
        if claim_status not in VALID_CLAIM_STATUSES:
            raise ValueError(f"Invalid claim_status {claim_status!r}")
        if debt_label not in VALID_DEBT_LABELS:
            raise ValueError(f"Invalid debt_label {debt_label!r}")

        state = self.load()
        deps = dependencies or []
        rank = {
            "conjectured": 0,
            "experimentally_supported": 1,
            "informally_justified": 2,
            "lean_statement_checked": 3,
            "lean_sketch_checked": 4,
            "lean_fully_checked": 5,
        }
        for art in state.formal_artifacts:
            if art.claim != claim:
                continue
            if proof_text:
                art.proof_text = proof_text
            if lean_statement:
                art.lean_statement = lean_statement
            if lean_sketch:
                art.lean_sketch = lean_sketch
            if deps:
                merged = list(dict.fromkeys([*art.dependencies, *deps]))
                art.dependencies = merged
            if rank[claim_status] >= rank.get(art.claim_status, 0):
                art.claim_status = claim_status
            if debt_label != "none" or art.debt_label == "none":
                art.debt_label = debt_label
            self.save(state)
            return

        state.formal_artifacts.append(
            FormalArtifact(
                claim=claim,
                proof_text=proof_text,
                claim_status=claim_status,
                debt_label=debt_label,
                lean_statement=lean_statement,
                lean_sketch=lean_sketch,
                dependencies=deps,
            )
        )
        self.save(state)

    # --- P7: Macro roadmap operations ---

    def set_macro_roadmap(
        self,
        macro_steps: list[MacroStep],
        *,
        roadmap_id: str | None = None,
        approach: str | None = None,
    ) -> None:
        """Set a hierarchical roadmap."""
        state = self.load()
        if roadmap_id is not None:
            state.current_roadmap_id = roadmap_id
        if approach is not None:
            state.current_approach = approach
        state.macro_roadmap = macro_steps
        # Also flatten sub-steps into current_roadmap for backward compat
        flat_steps: list[RoadmapStep] = []
        for ms in macro_steps:
            for step in ms.sub_steps:
                if state.current_roadmap_id and not step.roadmap_id:
                    step.roadmap_id = state.current_roadmap_id
                if not step.step_id:
                    base = step.roadmap_id or state.current_roadmap_id or "current-roadmap"
                    step.step_id = f"{base}:step:{step.step_index}"
            flat_steps.extend(ms.sub_steps)
        state.current_roadmap = flat_steps
        self.save(state)

    @staticmethod
    def _render_frontier(frontier: FrontierState | None) -> str | None:
        if frontier is None:
            return None
        lines = ["## Frontier\n"]
        if frontier.active_step_label:
            lines.append(f"- active step: {frontier.active_step_label}\n")
        if frontier.next_step_indices:
            lines.append(
                f"- next steps: {', '.join(str(v) for v in frontier.next_step_indices)}\n"
            )
        if frontier.open_obligations:
            lines.append(
                f"- open obligations: {', '.join(frontier.open_obligations)}\n"
            )
        if frontier.needed_proof_keys:
            lines.append(
                f"- needed proof keys: {', '.join(frontier.needed_proof_keys)}\n"
            )
        if frontier.current_blockers:
            lines.append("- blockers:\n")
            for blocker in frontier.current_blockers[:4]:
                lines.append(f"  - {blocker}\n")
        if frontier.last_update_event:
            lines.append(f"- last update: {frontier.last_update_event}\n")
        return "".join(lines).strip()

    @staticmethod
    def _render_obligations(
        obligations: list[ObligationRecord],
        *,
        max_chars: int = 2_500,
    ) -> str | None:
        if not obligations:
            return None
        lines = ["## Theorem Obligations\n"]
        total = len(lines[0])
        for item in obligations:
            support = ""
            if item.supporting_steps:
                support = f" steps={','.join(str(v) for v in item.supporting_steps[:4])}"
            if item.supporting_claim_ids:
                support += f" claims={','.join(item.supporting_claim_ids[:4])}"
            chunk = (
                f"- {item.obligation_id} [{item.status}]"
                f" :: {item.label}{support}\n"
            )
            if total + len(chunk) > max_chars:
                break
            lines.append(chunk)
            total += len(chunk)
        return "".join(lines).strip()

    @staticmethod
    def _render_proof_index(
        entries: list[ProofIndexEntry],
        *,
        max_chars: int = 3_000,
    ) -> str | None:
        if not entries:
            return None
        lines = ["## Proof Index\n"]
        total = len(lines[0])
        kept = 0
        for item in entries:
            tag = "suspect" if item.suspect else "trusted"
            deps = f" deps={','.join(item.dependencies[:4])}" if item.dependencies else ""
            chunk = (
                f"- {item.prop_id} [{tag}] note={item.note_key or item.note_id or item.prop_id}{deps}\n"
                f"  {item.summary or item.statement}\n"
            )
            if total + len(chunk) > max_chars:
                break
            lines.append(chunk)
            total += len(chunk)
            kept += 1
            if kept >= 8:
                break
        return "".join(lines).strip() if kept else None

    def render_for_planner(self, max_chars: int = 60_000) -> str | None:
        base = self.render_slim()
        ledger = self.render_failure_ledger(max_chars=min(8_000, max_chars // 4))
        graph = self.load().knowledge_graph.render_for_planner(max_chars=min(15_000, max_chars // 3))
        combined_parts = [part for part in [base, ledger, graph] if part]
        if not combined_parts:
            return None
        text = "\n\n".join(combined_parts)
        return text[:max_chars]

    def render_for_worker(self, step_query: str, max_chars: int = 12_000) -> str | None:
        state = self.load()
        proof_keys = state.knowledge_graph.select_relevant_claim_keys(
            step_query,
            max_items=4,
        )
        indexed_entries = [
            item for item in state.proof_index if item.prop_id in set(proof_keys)
        ]
        parts = [
            self._render_frontier(state.frontier),
            self._render_obligations(
                state.obligations,
                max_chars=min(2_000, max_chars // 4),
            ),
            self._render_proof_index(
                indexed_entries,
                max_chars=min(3_500, max_chars // 3),
            ),
            state.knowledge_graph.render_for_worker(step_query, max_chars=max_chars),
        ]
        text = "\n\n".join(part for part in parts if part).strip()
        return text[:max_chars] if text else None

    def select_worker_proof_keys(
        self,
        step_query: str,
        *,
        max_items: int = 4,
    ) -> list[str]:
        return self.load().knowledge_graph.select_relevant_claim_keys(
            step_query,
            max_items=max_items,
        )

    def render_for_reviewer(
        self,
        cited_claims: list[str] | None = None,
        max_chars: int = 5_000,
    ) -> str | None:
        state = self.load()
        text = state.knowledge_graph.render_for_reviewer(cited_claims, max_chars=max_chars)
        return text or None

    def render_failure_ledger(self, max_chars: int = 8_000) -> str | None:
        state = self.load()
        entries = self._sorted_failure_ledger(state)
        if not entries:
            return None
        lines = ["## Failure Ledger\n"]
        kept = 0
        total_chars = len(lines[0])
        for entry in entries:
            if entry.count < 2 and entry.diagnosis not in {
                "FALSE_PROPOSITION",
                "FALSIFIER_REJECTION",
                "REVIEW_GAP",
            }:
                continue
            block = [
                f"- x{entry.count} [{entry.diagnosis}] {entry.blocked_claim or entry.motif}\n",
                f"  motif: {entry.motif}\n" if entry.motif else "",
                f"  guidance: {entry.do_not_retry_guidance}\n",
            ]
            chunk = "".join(block)
            if total_chars + len(chunk) > max_chars:
                break
            lines.append(chunk)
            total_chars += len(chunk)
            kept += 1
            if kept >= 8:
                break
        if kept == 0:
            return None
        return "".join(lines).strip()

    # ------------------------------------------------------------------
    # Markdown rendering (human-readable + LLM context)
    # ------------------------------------------------------------------

    @staticmethod
    def _render_md(state: MemoState) -> str:
        """Render a MemoState to the MEMO.md format."""
        parts: list[str] = []

        # Current Roadmap
        parts.append("## Current Roadmap\n")
        if state.current_approach:
            parts.append(f"Approach: {state.current_approach}\n")
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

        frontier_text = Memo._render_frontier(state.frontier)
        if frontier_text:
            parts.append("\n" + frontier_text + "\n")

        obligations_text = Memo._render_obligations(state.obligations, max_chars=4_000)
        if obligations_text:
            parts.append("\n" + obligations_text + "\n")

        proof_index_text = Memo._render_proof_index(state.proof_index, max_chars=4_500)
        if proof_index_text:
            parts.append("\n" + proof_index_text + "\n")

        # Proved Propositions — split into trusted and suspect buckets.
        # Suspect propositions came from a roadmap the reviewer rejected;
        # they remain in the MEMO for planning visibility but must not be
        # invoked as premises without being re-proved from scratch.
        trusted_props = [p for p in state.proved_propositions if not p.suspect]
        suspect_props = [p for p in state.proved_propositions if p.suspect]

        parts.append("\n## Proved Propositions (reusable across roadmaps)\n")
        if trusted_props:
            for prop in trusted_props:
                lean_tag = " [lean: compiled]" if prop.lean_compiled else ""
                parts.append(
                    f"- {prop.prop_id}: {prop.statement} ({prop.source}){lean_tag}"
                    f"  [proof key: {prop.prop_id}]\n"
                )
        else:
            parts.append("(none yet)\n")

        if suspect_props:
            parts.append(
                "\n## Suspect Propositions (review-rejected; DO NOT invoke)\n"
            )
            parts.append(
                "These came from a roadmap the reviewer found gaps in. "
                "They may be false or unproven. Do NOT cite them as "
                "premises; re-prove from scratch if you need them.\n"
            )
            for prop in suspect_props:
                lean_tag = " [lean: compiled]" if prop.lean_compiled else ""
                parts.append(
                    f"- SUSPECT {prop.prop_id}: {prop.statement} ({prop.source}){lean_tag}"
                    f"  [proof key: {prop.prop_id}]\n"
                )

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
                if rm.artifact_summaries:
                    parts.append("Artifact summary:\n")
                    for summary in rm.artifact_summaries:
                        parts.append(f"  - {summary}\n")
                parts.append(f"Key lesson: {rm.lesson}\n\n")
        else:
            parts.append("(none yet)\n")

        # Runner-up Roadmaps
        if state.runner_up_roadmaps:
            parts.append("\n## Runner-up Roadmaps\n")
            for i, ru in enumerate(state.runner_up_roadmaps, 1):
                parts.append(f"### Runner-up {i}\n")
                parts.append(f"Approach: {ru.approach}\n")
                if ru.macro_steps:
                    for macro_index, macro in enumerate(ru.macro_steps, 1):
                        parts.append(
                            f"  Macro {macro_index}: {macro.get('description', '')}"
                            f" -> {macro.get('deliverable', '')}\n"
                        )
                        for j, s in enumerate(macro.get("steps", []), 1):
                            parts.append(f"    Step {j}: {s}\n")
                elif ru.steps:
                    for j, s in enumerate(ru.steps, 1):
                        parts.append(f"  Step {j}: {s}\n")
                parts.append(f"Reasoning: {ru.reasoning}\n\n")

        # P4: Pending Lemmas
        pending_lemmas = [lm for lm in state.lemma_queue if lm.status != "resolved"]
        if pending_lemmas:
            parts.append("\n## Pending Lemmas\n")
            for lm in pending_lemmas:
                unblock_str = f" (unblocks steps {lm.unblocks})" if lm.unblocks else ""
                parts.append(
                    f"- [{lm.lemma_type.upper()}] {lm.statement} "
                    f"(source: {lm.source}){unblock_str}\n"
                )

        # P3: Formal Artifacts (summary only)
        if state.formal_artifacts:
            parts.append("\n## Formal Artifacts\n")
            for art in state.formal_artifacts:
                debt_tag = f" [DEBT: {art.debt_label}]" if art.debt_label != "none" else ""
                parts.append(
                    f"- {art.claim[:80]} ... [{art.claim_status}]{debt_tag}\n"
                )

        # P7: Macro Roadmap
        if state.macro_roadmap:
            parts.append("\n## Macro Roadmap (hierarchical)\n")
            for ms in state.macro_roadmap:
                parts.append(
                    f"### Macro-step {ms.index}: {ms.description} [{ms.status}]\n"
                )
                parts.append(f"Deliverable: {ms.deliverable}\n")
                for sub in ms.sub_steps:
                    line = f"  Step {sub.step_index}: {sub.description} [{sub.status}]"
                    if sub.result:
                        line += f"\n    Result: {sub.result}"
                    parts.append(line + "\n")
                parts.append("\n")

        # Handoff
        if state.handoff:
            h = state.handoff
            parts.append("\n## Handoff (from previous context reset)\n")
            if h.roadmap_number:
                parts.append(f"Roadmap: {h.roadmap_number}\n")
            if h.current_step_index:
                parts.append(f"Current step: {h.current_step_index}\n")
            if h.next_action:
                parts.append(f"Next action: {h.next_action}\n")
            if h.current_strategy:
                parts.append(f"Current strategy: {h.current_strategy}\n")
            if h.proved_steps:
                parts.append(
                    f"Proved steps: {', '.join(str(i) for i in h.proved_steps)}\n"
                )
            if h.remaining_steps:
                parts.append(
                    f"Remaining steps: {', '.join(str(i) for i in h.remaining_steps)}\n"
                )
            if h.failed_steps:
                parts.append(
                    f"Failed steps: {', '.join(str(i) for i in h.failed_steps)}\n"
                )
            if h.reusable_prop_ids:
                parts.append(
                    f"Reusable propositions: {', '.join(h.reusable_prop_ids[:12])}\n"
                )
            if h.proof_keys:
                parts.append(
                    f"Proof keys: {', '.join(h.proof_keys[:12])}\n"
                )
            if h.active_step_label:
                parts.append(f"Active step label: {h.active_step_label}\n")
            if h.open_obligations:
                parts.append(
                    f"Open obligations: {', '.join(h.open_obligations[:8])}\n"
                )
            if h.recent_diagnoses:
                parts.append("Recent diagnoses:\n")
                for diagnosis in h.recent_diagnoses[:6]:
                    parts.append(f"  - {diagnosis}\n")
            if h.open_questions:
                parts.append("Open questions:\n")
                for q in h.open_questions:
                    parts.append(f"  - {q}\n")
            if h.blockers:
                parts.append("Blockers:\n")
                for b in h.blockers:
                    parts.append(f"  - {b}\n")
            parts.append(f"Confidence: {h.confidence:.2f}\n")

        if state.failure_ledger:
            parts.append("\n## Failure Ledger\n")
            for entry in sorted(
                state.failure_ledger,
                key=lambda item: (
                    item.count,
                    int(item.diagnosis in {"FALSE_PROPOSITION", "FALSIFIER_REJECTION"}),
                    item.last_attempt,
                ),
                reverse=True,
            )[:10]:
                parts.append(
                    f"- x{entry.count} [{entry.diagnosis}] {entry.blocked_claim or entry.motif}\n"
                )
                if entry.motif:
                    parts.append(f"  Motif: {entry.motif}\n")
                if entry.do_not_retry_guidance:
                    parts.append(f"  Guidance: {entry.do_not_retry_guidance}\n")

        if state.knowledge_graph.nodes:
            parts.append("\n## Knowledge Graph\n")
            parts.append(state.knowledge_graph.render_for_planner(max_chars=8_000))
            parts.append("\n")

        return "".join(parts)

    def render_slim(self) -> str | None:
        """Compact MEMO view for roadmap-generation prompts.

        Returns a trimmed rendering that fits comfortably within the
        backend's input budget.  Excluded (the main bloat sources):

        * **Suspect propositions** — replaced by a one-line count.
        * **Archived roadmap artifact summaries & step-failure details** —
          only approach + failure reason + lesson are kept.
        * **Runner-up roadmaps** — omitted entirely.
        * **Formal artifact details** — omitted entirely.
        * **Macro roadmap sub-step detail** — status line only.

        Returns ``None`` when the state carries no prior context
        (i.e. first attempt with no proved propositions and no previous
        roadmaps), so the caller can fall through to the ``count=3``
        first-attempt path unchanged.
        """
        state = self.load()
        if (
            not state.previous_roadmaps
            and not state.proved_propositions
            and not state.current_roadmap
            and not state.obligations
            and state.frontier is None
            and not state.proof_index
        ):
            return None

        parts: list[str] = []

        frontier_text = self._render_frontier(state.frontier)
        if frontier_text:
            parts.append(frontier_text + "\n\n")

        obligations_text = self._render_obligations(
            state.obligations,
            max_chars=2_500,
        )
        if obligations_text:
            parts.append(obligations_text + "\n\n")

        proof_index_text = self._render_proof_index(
            [item for item in state.proof_index if not item.suspect],
            max_chars=2_500,
        )
        if proof_index_text:
            parts.append(proof_index_text + "\n\n")

        # Current Roadmap (compact — one line per step)
        parts.append("## Current Roadmap\n")
        if state.current_approach:
            parts.append(f"Approach: {state.current_approach}\n")
        if state.current_roadmap:
            for step in state.current_roadmap:
                parts.append(
                    f"Step {step.step_index}: {step.description} [{step.status}]\n"
                )
        else:
            parts.append("(none)\n")

        # Trusted Propositions (full — usually small)
        trusted = [p for p in state.proved_propositions if not p.suspect]
        parts.append("\n## Proved Propositions (reusable across roadmaps)\n")
        if trusted:
            for prop in trusted:
                lean_tag = " [lean: compiled]" if prop.lean_compiled else ""
                parts.append(
                    f"- {prop.prop_id}: {prop.statement} ({prop.source}){lean_tag}"
                    f"  [proof key: {prop.prop_id}]\n"
                )
        else:
            parts.append("(none yet)\n")

        # Suspect Propositions — count only, not the full list
        n_suspect = sum(1 for p in state.proved_propositions if p.suspect)
        if n_suspect:
            parts.append(
                f"\n({n_suspect} suspect proposition(s) from review-rejected "
                f"roadmaps omitted — do not cite them as premises.)\n"
            )

        # Refuted Propositions (essential — keep full)
        if state.refuted_propositions:
            parts.append("\n## Refuted Propositions (DO NOT RETRY these claims)\n")
            for rp in state.refuted_propositions:
                parts.append(f"- FALSE: {rp.false_claim or rp.description}\n")
                parts.append(f"  Reason: {rp.explanation}\n")

        # Previous Roadmaps — compact (no artifact summaries, no step details)
        parts.append("\n## Previous Roadmaps\n")
        if state.previous_roadmaps:
            for rm in state.previous_roadmaps:
                review_tag = " [REVIEW-REJECTED]" if _is_review_rejected(rm) else ""
                parts.append(f"- {rm.name}{review_tag}: {rm.approach}\n")
                parts.append(f"  Failed: {rm.failure_reason}\n")
                if rm.lesson:
                    parts.append(f"  Lesson: {rm.lesson}\n")
        else:
            parts.append("(none yet)\n")

        # Pending Lemmas (if any — usually small)
        pending = [lm for lm in state.lemma_queue if lm.status != "resolved"]
        if pending:
            parts.append("\n## Pending Lemmas\n")
            for lm in pending:
                unblock = f" (unblocks steps {lm.unblocks})" if lm.unblocks else ""
                parts.append(
                    f"- [{lm.lemma_type.upper()}] {lm.statement}{unblock}\n"
                )

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
