"""Phase 1 loop: mathematical proof (roadmap -> execute -> review).

This is the core loop that implements the architecture from AGENT.md:
1. Roadmap Generation (3 on first attempt, 1 on subsequent)
   - Runner-up roadmaps stored for fallback (P4)
2. Execution Loop (step-by-step proving with verification)
3. Review (forked Review Agent + blind Falsifier)
4. Structured handoff on context resets (P6)
"""

from __future__ import annotations

import asyncio
import copy
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from math_agent.agents.thinking import ThinkingAgent
from math_agent.agents.formalizer import FormalizerAgent
from math_agent.agents.assistant import AssistantAgent
from math_agent.agents.review import ReviewAgent
from math_agent.agents.falsifier import FalsifierAgent
from math_agent.agents.base import StepResult, RoadmapEvaluation, ReviewResult
from math_agent.documents.memo import (
    AuxiliaryLemma,
    MacroStep,
    Memo,
    MemoState,
    RoadmapStep,
    HandoffPacket,
    StepFailure,
)
from math_agent.documents.notes import Notes
from math_agent.context.token_budget import TokenBudget
from math_agent.context.compression import ContextCompressor
from math_agent.context.prompt_assembler import (
    AssemblyResult,
    PromptAssembler,
    PromptSection,
    PromptVariant,
)
from math_agent.context.diminishing import DiminishingReturnsDetector, ProgressEntry
from math_agent.config import Hyperparameters, PromptBudgetConfig
from math_agent.runtime import AgentRuntimeSession, InputTooLargeError, RuntimeMessage

logger = logging.getLogger(__name__)


@dataclass
class ThinkingEvent:
    """Event emitted during Phase 1 for the Thinking Process panel."""

    event_type: str  # roadmap_generated | step_started | step_verified | step_failed | roadmap_reevaluated | review_started | review_result | gap_repair | falsifier_started | falsifier_result | compression | handoff | abandoned
    step_index: int | None = None
    content: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class Phase1Result:
    """Result of Phase 1."""

    success: bool
    complete_proof: str = ""
    memo_state: MemoState | None = None
    events: list[ThinkingEvent] = field(default_factory=list)
    roadmaps_attempted: int = 0


class Phase1Runner:
    """Phase 1: Mathematical Proof.

    Depth-first roadmap execution with step verification,
    progressive compression, diminishing-returns detection,
    runner-up roadmap fallback, and structured handoff on
    context resets.
    """

    def __init__(
        self,
        thinking: ThinkingAgent,
        assistant: AssistantAgent,
        memo: Memo,
        notes: Notes,
        hyper: Hyperparameters,
        problem_question: str,
        formalizer: FormalizerAgent | None = None,
        falsifier: FalsifierAgent | None = None,
        review_runtime: AgentRuntimeSession | None = None,
        toolplane: "Any | None" = None,
        prompt_budgets: PromptBudgetConfig | None = None,
    ):
        self.thinking = thinking
        self.assistant = assistant
        self.memo = memo
        self.notes = notes
        self.hyper = hyper
        self.prompt_budgets = prompt_budgets or PromptBudgetConfig()
        self.problem = problem_question
        self.formalizer = formalizer
        self.falsifier = falsifier
        self.review_runtime = review_runtime
        self.toolplane = toolplane  # P2: Lean-in-Phase-1
        self.budget = TokenBudget()
        self.compressor = ContextCompressor(self.budget, thinking.runtime)
        self.detector = DiminishingReturnsDetector(window=hyper.K)
        self.assembler = PromptAssembler()
        self._events: list[ThinkingEvent] = []
        self._roadmaps_attempted = 0
        self._assembly_bias: dict[str, int] = {}
        self._resume_approach: str | None = None

    def _emit(self, event: ThinkingEvent) -> None:
        self._events.append(event)
        logger.info(
            "Phase1 [%s] step=%s: %s",
            event.event_type,
            event.step_index,
            event.content[:120],
        )

    def _update_assembly_bias(self, callsite: str, result: AssemblyResult) -> None:
        current = self._assembly_bias.get(callsite, 0)
        if result.near_limit:
            self._assembly_bias[callsite] = min(current + 1, 3)
        elif current > 0:
            self._assembly_bias[callsite] = current - 1

    def _handoff_context_message(self, handoff: HandoffPacket) -> str:
        lines = [
            "Structured handoff from prior context reset:",
            f"- roadmap: {handoff.roadmap_number}",
            f"- current step: {handoff.current_step_index or 'n/a'}",
            f"- next action: {handoff.next_action}",
        ]
        if handoff.roadmap_id:
            lines.append(f"- roadmap id: {handoff.roadmap_id}")
        if handoff.current_step_id:
            lines.append(f"- current step id: {handoff.current_step_id}")
        if handoff.proved_steps:
            lines.append(
                f"- proved steps: {', '.join(str(i) for i in handoff.proved_steps)}"
            )
        if handoff.remaining_steps:
            lines.append(
                f"- remaining steps: {', '.join(str(i) for i in handoff.remaining_steps)}"
            )
        if handoff.failed_steps:
            lines.append(
                f"- failed steps: {', '.join(str(i) for i in handoff.failed_steps)}"
            )
        if handoff.reusable_prop_ids:
            lines.append(
                f"- reusable propositions: {', '.join(handoff.reusable_prop_ids[:12])}"
            )
        if handoff.proof_keys:
            lines.append(f"- proof keys: {', '.join(handoff.proof_keys[:12])}")
        if handoff.proof_note_ids:
            lines.append(f"- proof note ids: {', '.join(handoff.proof_note_ids[:8])}")
        if handoff.proof_summaries:
            lines.append("Proof summaries:")
            lines.extend(f"  - {item}" for item in handoff.proof_summaries[:4])
        if handoff.active_step_label:
            lines.append(f"- active step label: {handoff.active_step_label}")
        if handoff.open_obligations:
            lines.append(
                f"- open obligations: {', '.join(handoff.open_obligations[:8])}"
            )
        if handoff.recent_diagnoses:
            lines.append("Recent diagnoses:")
            lines.extend(f"  - {item}" for item in handoff.recent_diagnoses[:6])
        return "\n".join(lines)

    @staticmethod
    def _macro_steps_from_choice(chosen: dict[str, Any]) -> list[MacroStep] | None:
        """Convert optional roadmap macro_steps into runtime MacroStep objects."""
        raw_macros = chosen.get("macro_steps", [])
        if not raw_macros:
            return None

        macro_steps: list[MacroStep] = []
        next_step_index = 1
        for macro_index, raw_macro in enumerate(raw_macros, start=1):
            sub_steps: list[RoadmapStep] = []
            for offset, desc in enumerate(raw_macro.get("steps", []), start=0):
                obligations_raw = raw_macro.get("step_obligations", [])
                obligations = (
                    [str(item) for item in obligations_raw[offset] if str(item).strip()]
                    if isinstance(obligations_raw, list)
                    and offset < len(obligations_raw)
                    and isinstance(obligations_raw[offset], list)
                    else []
                )
                sub_steps.append(
                    RoadmapStep(
                        step_index=next_step_index,
                        description=str(desc),
                        status="UNPROVED",
                        downstream_obligations=obligations,
                    )
                )
                next_step_index += 1
            macro_steps.append(
                MacroStep(
                    index=macro_index,
                    description=str(raw_macro.get("description", f"Macro-step {macro_index}")),
                    deliverable=str(raw_macro.get("deliverable", "")).strip(),
                    sub_steps=sub_steps,
                )
            )
            macro_steps[-1].update_status()
        return macro_steps

    @staticmethod
    def _flatten_macro_steps(macro_steps: list[MacroStep]) -> list[RoadmapStep]:
        flat_steps: list[RoadmapStep] = []
        for macro in macro_steps:
            flat_steps.extend(macro.sub_steps)
        return flat_steps

    @staticmethod
    def _renumber_macro_steps(macro_steps: list[MacroStep]) -> None:
        """Keep sub-step indices globally sequential after macro rewrites."""
        next_index = 1
        for macro in macro_steps:
            for step in macro.sub_steps:
                step.step_index = next_index
                next_index += 1

    @classmethod
    def _macro_matches_current(
        cls,
        macro_steps: list[MacroStep] | None,
        current_steps: list[RoadmapStep],
    ) -> bool:
        if not macro_steps:
            return True
        flat = cls._flatten_macro_steps(macro_steps)
        if len(flat) != len(current_steps):
            return False
        for macro_step, current_step in zip(flat, current_steps, strict=False):
            if (
                macro_step.step_index != current_step.step_index
                or macro_step.description != current_step.description
                or macro_step.status != current_step.status
            ):
                return False
        return True

    def _sanitize_resume_macro_state(self, memo_state: MemoState) -> MemoState:
        if self._macro_matches_current(
            memo_state.macro_roadmap,
            memo_state.current_roadmap,
        ):
            return memo_state
        logger.warning(
            "Discarding stale macro_roadmap that no longer matches current_roadmap."
        )
        memo_state.macro_roadmap = None
        self.memo.set_current_roadmap(
            memo_state.current_roadmap,
            roadmap_id=memo_state.current_roadmap_id or None,
            approach=memo_state.current_approach or None,
        )
        self._emit(
            ThinkingEvent(
                "resume_macro_sanitized",
                content=(
                    "Discarded stale macro roadmap state and resumed from the flat roadmap."
                ),
            )
        )
        return memo_state

    @staticmethod
    def _current_roadmap_payload(
        steps: list[RoadmapStep],
        macro_steps: list[MacroStep] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "current_roadmap": [
                {
                    "step_index": step.step_index,
                    "step_id": step.step_id,
                    "roadmap_id": step.roadmap_id,
                    "description": step.description,
                    "status": step.status,
                    "lean_status": step.lean_status,
                    "obligations": step.downstream_obligations,
                }
                for step in steps
            ]
        }
        if macro_steps:
            payload["macro_roadmap"] = [
                {
                    "index": macro.index,
                    "description": macro.description,
                    "deliverable": macro.deliverable,
                    "status": macro.status,
                    "sub_steps": [
                        {
                            "step_index": step.step_index,
                            "step_id": step.step_id,
                            "roadmap_id": step.roadmap_id,
                            "description": step.description,
                            "status": step.status,
                            "lean_status": step.lean_status,
                            "obligations": step.downstream_obligations,
                        }
                        for step in macro.sub_steps
                    ],
                }
                for macro in macro_steps
            ]
        return payload

    def _run_id(self) -> str:
        return self.memo.json_path.parent.name

    def _roadmap_id_for_attempt(self, attempt: int) -> str:
        return f"{self._run_id()}-roadmap-{attempt}"

    def _assign_step_identity(
        self,
        steps: list[RoadmapStep],
        *,
        roadmap_id: str,
    ) -> None:
        for step in steps:
            step.roadmap_id = roadmap_id
            if not step.step_id:
                step.step_id = f"{roadmap_id}:step:{step.step_index}"

    @staticmethod
    def _choice_step_obligations(choice: dict[str, Any], index: int) -> list[str]:
        raw = choice.get("step_obligations", [])
        if isinstance(raw, list) and index < len(raw) and isinstance(raw[index], list):
            return [str(item) for item in raw[index] if str(item).strip()]
        return []

    @staticmethod
    def _structured_premises_text(steps: list[RoadmapStep]) -> str:
        """Render proved checkpoint steps as explicit premises."""
        proved = [step for step in steps if step.status == "PROVED"]
        if not proved:
            return ""

        lines = ["Established premises from verified checkpoint steps:"]
        for step in proved:
            claim = step.claim or step.description
            lines.append(f"- Step {step.step_index}: {claim}")
            if step.proof_text:
                lines.append(f"  Proof summary: {step.proof_text[:240]}")
            if step.lean_status:
                lines.append(f"  Lean status: {step.lean_status}")
        return "\n".join(lines)

    def _inject_structured_premises(self, steps: list[RoadmapStep]) -> None:
        """Push proved checkpoint steps back into the LLM context after reset/resume."""
        premises = self._structured_premises_text(steps)
        if premises:
            self.thinking.add_to_context(RuntimeMessage(role="user", content=premises))

    @staticmethod
    def _build_roadmap_summary(
        approach: str,
        steps: list[RoadmapStep],
        macro_steps: list[MacroStep] | None = None,
        active_macro: MacroStep | None = None,
    ) -> str:
        """Build either a flat or hierarchical roadmap summary."""
        if not macro_steps:
            return approach + "\n" + "\n".join(
                f"Step {s.step_index}: {s.description} [{s.status}]"
                for s in steps
            )

        completed_deliverables = [
            f"Macro {macro.index}: {macro.deliverable}"
            for macro in macro_steps
            if macro.status == "PROVED"
        ]
        parts = [approach]
        if completed_deliverables:
            parts.append("Completed macro-step deliverables:")
            parts.extend(f"- {item}" for item in completed_deliverables)

        if active_macro is not None:
            parts.append(
                f"Current macro-step {active_macro.index}: "
                f"{active_macro.description} -> {active_macro.deliverable}"
            )
            for sub in active_macro.sub_steps:
                parts.append(
                    f"Step {sub.step_index}: {sub.description} [{sub.status}]"
                )
        else:
            for macro in macro_steps:
                parts.append(
                    f"Macro {macro.index}: {macro.description} "
                    f"(deliverable: {macro.deliverable}) [{macro.status}]"
                )

        return "\n".join(parts)

    @staticmethod
    def _truncate_for_budget(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        marker = "\n\n[... truncated for prompt budget ...]\n\n"
        head = max_chars * 2 // 3
        tail = max(max_chars - head - len(marker), 0)
        return text[:head] + marker + text[-tail:]

    @staticmethod
    def _obligation_descriptions() -> dict[str, str]:
        return {
            "necessary_direction": "prove the necessary / only-if direction",
            "sufficiency_direction": "prove the sufficient / converse direction",
            "existence_or_construction": "construct or exhibit the required object and verify it works",
            "boundary_or_small_cases": "check boundary, degenerate, or small cases explicitly",
            "final_target_link": "explicitly conclude the original theorem from the proved ingredients",
        }

    @classmethod
    def _required_obligation_keys(cls, problem_question: str) -> list[str]:
        text = f" {problem_question.lower()} "
        obligations: list[str] = []

        def add(kind: str) -> None:
            if kind not in obligations:
                obligations.append(kind)

        if (
            "if and only if" in text
            or re.search(r"\biff\b", text)
            or " equivalent " in text
            or "equivalence" in text
        ):
            add("necessary_direction")
            add("sufficiency_direction")

        if any(
            marker in text
            for marker in (
                "find all",
                " characterize",
                " determine which",
                " classify",
            )
        ):
            add("necessary_direction")
            add("sufficiency_direction")
            add("boundary_or_small_cases")

        if any(
            marker in text
            for marker in (
                "there exists",
                "there is a",
                "there is an",
                "construct",
                "build",
                "exhibit",
                "define a",
                "define an",
            )
        ):
            add("existence_or_construction")

        add("final_target_link")
        return obligations

    @classmethod
    def _format_required_obligations(cls, obligation_keys: list[str]) -> list[str]:
        descriptions = cls._obligation_descriptions()
        return [
            f"{key}: {descriptions[key]}"
            for key in obligation_keys
            if key in descriptions
        ]

    @classmethod
    def _normalize_obligation_key(cls, raw: str) -> str:
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
    def _obligations_for_text(cls, text: str) -> set[str]:
        lowered = " ".join((text or "").lower().split())
        hits: set[str] = set()

        if any(token in lowered for token in ("necessary", "only if", "constraint", "derive necessary", "must satisfy")):
            hits.add("necessary_direction")
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
            hits.add("sufficiency_direction")
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
            hits.add("existence_or_construction")
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
            hits.add("boundary_or_small_cases")
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
            hits.add("final_target_link")

        # Construction often simultaneously serves the sufficiency direction.
        if "existence_or_construction" in hits and any(
            token in lowered for token in ("verify", "satisfies", "works", "sigma-good")
        ):
            hits.add("sufficiency_direction")
        return hits

    def _annotate_step_obligations(self, steps: list[RoadmapStep]) -> None:
        for step in steps:
            inferred = sorted(self._obligations_for_text(step.description))
            combined = list(dict.fromkeys([*step.downstream_obligations, *inferred]))
            if combined:
                step.downstream_obligations = combined

    def _roadmap_coverage(self, steps: list[RoadmapStep]) -> dict[str, set[str] | list[str]]:
        required = self._required_obligation_keys(self.problem)
        covered_all: set[str] = set()
        covered_proved: set[str] = set()
        for step in steps:
            obligations = set(step.downstream_obligations) | self._obligations_for_text(
                step.description
            )
            covered_all.update(obligations)
            if step.status == "PROVED":
                covered_proved.update(obligations)
        return {
            "required": required,
            "covered_all": covered_all,
            "covered_proved": covered_proved,
            "missing_total": [key for key in required if key not in covered_all],
            "missing_after_proved": [key for key in required if key not in covered_proved],
        }

    def _proved_steps_payload(self, steps: list[RoadmapStep]) -> list[dict[str, str | int]]:
        payload: list[dict[str, str | int]] = []
        for step in steps:
            if step.status != "PROVED":
                continue
            payload.append(
                {
                    "index": step.step_index,
                    "description": step.description,
                    "claim": step.claim or step.description,
                    "result": step.result or "",
                    "obligations": ", ".join(step.downstream_obligations),
                }
            )
        return payload

    def _apply_updated_steps_to_scope(
        self,
        scope: list[RoadmapStep],
        updated_steps: list[dict],
    ) -> bool:
        changed = False
        by_index = {step.step_index: step for step in scope}
        roadmap_id = next((step.roadmap_id for step in scope if step.roadmap_id), "")
        for updated in updated_steps:
            if not isinstance(updated, dict):
                continue
            idx = updated.get("index")
            new_desc = str(updated.get("description", "")).strip()
            raw_obligations = updated.get("obligations", [])
            obligations = [
                self._normalize_obligation_key(item)
                for item in raw_obligations
                if self._normalize_obligation_key(item)
            ] if isinstance(raw_obligations, list) else []
            if not idx or not new_desc:
                continue
            existing = by_index.get(idx)
            if existing is not None:
                if existing.status == "UNPROVED" and (
                    existing.description != new_desc
                    or obligations != existing.downstream_obligations
                ):
                    existing.description = new_desc
                    existing.downstream_obligations = obligations
                    changed = True
                continue
            scope.append(
                RoadmapStep(
                    step_index=int(idx),
                    description=new_desc,
                    status="UNPROVED",
                    roadmap_id=roadmap_id,
                    step_id=f"{roadmap_id}:step:{int(idx)}" if roadmap_id else "",
                    downstream_obligations=obligations,
                )
            )
            changed = True
        scope.sort(key=lambda step: step.step_index)
        return changed

    def _coverage_losses_from_update(
        self,
        scope: list[RoadmapStep],
        updated_steps: list[dict],
    ) -> list[str]:
        preview_scope = copy.deepcopy(scope)
        self._apply_updated_steps_to_scope(preview_scope, updated_steps)
        self._annotate_step_obligations(preview_scope)
        before = self._roadmap_coverage(scope)
        after = self._roadmap_coverage(preview_scope)
        losses: list[str] = []
        before_proved = before["covered_proved"]
        before_all = before["covered_all"]
        after_all = after["covered_all"]
        for key in before["required"]:
            if key in before_proved:
                continue
            if key in before_all and key not in after_all:
                losses.append(key)
        return losses

    @classmethod
    def _synthesize_missing_steps(cls, obligation_keys: list[str]) -> list[str]:
        mapping = {
            "necessary_direction": "Prove the necessary direction explicitly: derive the required constraints from the original hypothesis.",
            "sufficiency_direction": "Prove the sufficiency/converse direction explicitly and verify it satisfies the full theorem.",
            "existence_or_construction": "Construct or exhibit the required object and verify it has the claimed property.",
            "boundary_or_small_cases": "Check the remaining boundary, degenerate, or small cases explicitly.",
            "final_target_link": "Combine the proved ingredients to derive the exact original theorem statement.",
        }
        result: list[str] = []
        for raw in obligation_keys:
            key = cls._normalize_obligation_key(raw)
            step = mapping.get(key)
            if step and step not in result:
                result.append(step)
        return result

    def _append_steps_for_missing_obligations(
        self,
        *,
        steps: list[RoadmapStep],
        macro_steps: list[MacroStep] | None,
        missing_obligations: list[str],
        explicit_steps: list[str] | None = None,
    ) -> list[str]:
        new_descriptions = [
            desc.strip()
            for desc in (explicit_steps or self._synthesize_missing_steps(missing_obligations))
            if desc.strip()
        ]
        if not new_descriptions:
            return []

        start_index = max((step.step_index for step in steps), default=0) + 1
        new_steps = [
            RoadmapStep(
                step_index=start_index + offset,
                description=description,
                status="UNPROVED",
                roadmap_id=steps[0].roadmap_id if steps else "",
                step_id=(
                    f"{steps[0].roadmap_id}:step:{start_index + offset}"
                    if steps and steps[0].roadmap_id
                    else ""
                ),
                downstream_obligations=[
                    self._normalize_obligation_key(item)
                    for item in missing_obligations
                    if self._normalize_obligation_key(item)
                ],
            )
            for offset, description in enumerate(new_descriptions)
        ]
        if macro_steps:
            macro_steps[-1].sub_steps.extend(new_steps)
            self._renumber_macro_steps(macro_steps)
            self._sync_macro_roadmap(macro_steps)
            steps[:] = self._flatten_macro_steps(macro_steps)
        else:
            steps.extend(new_steps)
            steps.sort(key=lambda step: step.step_index)
            self.memo.set_current_roadmap(
                steps,
                roadmap_id=steps[0].roadmap_id if steps else None,
            )
        self._annotate_step_obligations(steps)
        if macro_steps:
            for macro in macro_steps:
                macro.update_status()
        return new_descriptions

    async def _ensure_pre_review_completeness(
        self,
        *,
        approach: str,
        steps: list[RoadmapStep],
        macro_steps: list[MacroStep] | None,
        roadmap_summary: str,
    ) -> tuple[bool, str]:
        self._annotate_step_obligations(steps)
        coverage = self._roadmap_coverage(steps)
        required_keys = coverage["required"]
        assessment = await self.thinking.assess_completeness(
            self.problem,
            roadmap_summary,
            self._proved_steps_payload(steps),
            self._format_required_obligations(required_keys),
        )
        if assessment.is_complete:
            return True, roadmap_summary

        missing_keys = [
            self._normalize_obligation_key(item)
            for item in assessment.missing_obligations
            if self._normalize_obligation_key(item)
        ]
        if not missing_keys:
            missing_keys = [
                key for key in coverage["missing_after_proved"] if isinstance(key, str)
            ]
        appended = self._append_steps_for_missing_obligations(
            steps=steps,
            macro_steps=macro_steps,
            missing_obligations=missing_keys,
            explicit_steps=assessment.missing_steps or None,
        )
        if not appended:
            self._emit(
                ThinkingEvent(
                    "completeness_failed",
                    content=assessment.reasoning,
                    metadata={"missing_obligations": missing_keys},
                )
            )
            return False, roadmap_summary

        updated_summary = self._build_roadmap_summary(
            approach,
            steps,
            macro_steps,
        )
        self._emit(
            ThinkingEvent(
                "roadmap_extended",
                content=(
                    "Completed steps were not yet a full theorem proof. "
                    "Added missing roadmap steps before review."
                ),
                metadata={
                    "missing_obligations": missing_keys,
                    "added_steps": appended,
                    "assessment": assessment.reasoning,
                    **self._current_roadmap_payload(steps, macro_steps),
                },
            )
        )
        return False, updated_summary

    def _assemble_planner_memory(self) -> AssemblyResult:
        state = self.memo.load()
        slim = self.memo.render_slim() or ""
        ledger = self.memo.render_failure_ledger(
            max_chars=min(8_000, self.prompt_budgets.roadmap_generation // 4)
        ) or ""
        graph = state.knowledge_graph.render_for_planner(
            max_chars=min(15_000, self.prompt_budgets.roadmap_generation // 3)
        )
        result = self.assembler.fit(
            [
                PromptSection(
                    name="slim_memo",
                    priority=3,
                    variants=[
                        PromptVariant("full", slim),
                        PromptVariant(
                            "compact",
                            self._truncate_for_budget(slim, min(12_000, max(4_000, len(slim) // 2)))
                            if slim
                            else "",
                        ),
                        PromptVariant("none", ""),
                    ],
                ),
                PromptSection(
                    name="failure_ledger",
                    priority=1,
                    variants=[
                        PromptVariant("full", ledger),
                        PromptVariant(
                            "compact",
                            self._truncate_for_budget(ledger, min(4_000, max(1_500, len(ledger) // 2)))
                            if ledger
                            else "",
                        ),
                        PromptVariant("none", ""),
                    ],
                ),
                PromptSection(
                    name="graph",
                    priority=2,
                    variants=[
                        PromptVariant("full", graph),
                        PromptVariant(
                            "compact",
                            self._truncate_for_budget(graph, min(6_000, max(2_000, len(graph) // 2)))
                            if graph
                            else "",
                        ),
                        PromptVariant("none", ""),
                    ],
                ),
            ],
            builder=lambda selected: "\n\n".join(
                part for part in [
                    selected.get("slim_memo", ""),
                    selected.get("failure_ledger", ""),
                    selected.get("graph", ""),
                ] if part
            ),
            max_chars=self.prompt_budgets.roadmap_generation,
            degrade_bias=self._assembly_bias.get("roadmap_generation", 0),
        )
        self._update_assembly_bias("roadmap_generation", result)
        return result

    def _assemble_worker_context(
        self,
        *,
        steps: list[RoadmapStep],
        step: RoadmapStep,
        repair_feedback: str,
    ) -> AssemblyResult:
        premises = self._structured_premises_text(steps)
        worker_memory = self.memo.render_for_worker(
            step.description,
            max_chars=self.prompt_budgets.step_work,
        ) or ""
        proof_keys = self.memo.select_worker_proof_keys(step.description, max_items=4)
        keyed_notes = self.notes.render_for_worker(
            relevant_keys=proof_keys or None,
            max_chars=min(5_000, self.prompt_budgets.step_work // 2),
        )
        result = self.assembler.fit(
            [
                PromptSection(
                    name="premises",
                    priority=4,
                    variants=[
                        PromptVariant("full", premises),
                        PromptVariant(
                            "compact",
                            self._truncate_for_budget(premises, min(4_500, max(1_500, len(premises) // 2)))
                            if premises
                            else "",
                        ),
                        PromptVariant("none", ""),
                    ],
                ),
                PromptSection(
                    name="worker_memory",
                    priority=3,
                    variants=[
                        PromptVariant("full", worker_memory),
                        PromptVariant(
                            "compact",
                            self._truncate_for_budget(worker_memory, min(4_000, max(1_500, len(worker_memory) // 2)))
                            if worker_memory
                            else "",
                        ),
                        PromptVariant("none", ""),
                    ],
                ),
                PromptSection(
                    name="keyed_notes",
                    priority=2,
                    variants=[
                        PromptVariant("full", keyed_notes),
                        PromptVariant(
                            "compact",
                            self._truncate_for_budget(keyed_notes, min(3_000, max(1_200, len(keyed_notes) // 2)))
                            if keyed_notes
                            else "",
                        ),
                        PromptVariant("none", ""),
                    ],
                ),
                PromptSection(
                    name="repair_feedback",
                    priority=5,
                    variants=[
                        PromptVariant("full", repair_feedback),
                        PromptVariant(
                            "compact",
                            self._truncate_for_budget(repair_feedback, min(2_000, max(800, len(repair_feedback) // 2)))
                            if repair_feedback
                            else "",
                        ),
                        PromptVariant("none", ""),
                    ],
                ),
            ],
            builder=lambda selected: "\n\n".join(
                part
                for part in [
                    selected.get("premises", ""),
                    f"Relevant prior memory:\n{selected['worker_memory']}"
                    if selected.get("worker_memory")
                    else "",
                    f"Reusable proof notes:\n{selected['keyed_notes']}"
                    if selected.get("keyed_notes")
                    else "",
                    selected.get("repair_feedback", ""),
                ]
                if part
            ),
            max_chars=self.prompt_budgets.step_work,
            degrade_bias=self._assembly_bias.get("step_work", 0),
        )
        self._update_assembly_bias("step_work", result)
        return result

    def _assemble_review_context(
        self,
        *,
        roadmap_summary: str,
        cited_claims: list[str],
        max_chars: int | None = None,
    ) -> AssemblyResult:
        budget = max_chars or self.prompt_budgets.review
        trust_summary = self.memo.render_for_reviewer(
            cited_claims=cited_claims,
            max_chars=budget,
        ) or ""
        result = self.assembler.fit(
            [
                PromptSection(
                    name="roadmap_summary",
                    priority=4,
                    variants=[
                        PromptVariant("full", roadmap_summary),
                        PromptVariant(
                            "compact",
                            self._truncate_for_budget(roadmap_summary, min(4_000, max(1_500, len(roadmap_summary) // 2))),
                        ),
                        PromptVariant("none", ""),
                    ],
                ),
                PromptSection(
                    name="trust_summary",
                    priority=3,
                    variants=[
                        PromptVariant("full", trust_summary),
                        PromptVariant(
                            "compact",
                            self._truncate_for_budget(trust_summary, min(3_500, max(1_200, len(trust_summary) // 2)))
                            if trust_summary
                            else "",
                        ),
                        PromptVariant("none", ""),
                    ],
                ),
            ],
            builder=lambda selected: "\n\n".join(
                part for part in [
                    selected.get("roadmap_summary", ""),
                    selected.get("trust_summary", ""),
                ] if part
            ),
            max_chars=budget,
            degrade_bias=self._assembly_bias.get("review", 0),
        )
        self._update_assembly_bias("review", result)
        return result

    def _assemble_proof_payload(
        self,
        *,
        complete_proof: str,
        max_chars: int,
        bias_key: str,
    ) -> AssemblyResult:
        synopsis = self._truncate_for_budget(
            complete_proof,
            min(max_chars, max(4_000, len(complete_proof) // 4)),
        )
        result = self.assembler.fit(
            [
                PromptSection(
                    name="proof",
                    priority=4,
                    variants=[
                        PromptVariant("full", complete_proof),
                        PromptVariant(
                            "compact",
                            self._truncate_for_budget(
                                complete_proof,
                                min(max_chars, max(8_000, len(complete_proof) // 2)),
                            ),
                        ),
                        PromptVariant("synopsis", synopsis),
                    ],
                ),
            ],
            builder=lambda selected: selected.get("proof", ""),
            max_chars=max_chars,
            degrade_bias=self._assembly_bias.get(bias_key, 0),
        )
        self._update_assembly_bias(bias_key, result)
        return result

    def _assemble_review_package(
        self,
        *,
        complete_proof: str,
        roadmap_summary: str,
        cited_claims: list[str],
    ) -> tuple[AssemblyResult, AssemblyResult]:
        context_budget = min(8_000, max(3_500, self.prompt_budgets.review // 3))
        review_context = self._assemble_review_context(
            roadmap_summary=roadmap_summary,
            cited_claims=cited_claims,
            max_chars=context_budget,
        )
        proof_budget = max(
            6_000,
            self.prompt_budgets.review - review_context.chars - len(self.problem) - 2_000,
        )
        review_proof = self._assemble_proof_payload(
            complete_proof=complete_proof,
            max_chars=proof_budget,
            bias_key="review_proof",
        )
        return review_context, review_proof

    def _assemble_repair_package(
        self,
        *,
        complete_proof: str,
        gaps: list[str],
        reviewer_reasoning: str,
    ) -> tuple[AssemblyResult, str]:
        reserve = len(self.problem) + len("\n".join(gaps)) + len(reviewer_reasoning) + 2_500
        proof_budget = max(
            12_000,
            self.prompt_budgets.proof_compilation - reserve,
        )
        repair_proof = self._assemble_proof_payload(
            complete_proof=complete_proof,
            max_chars=proof_budget,
            bias_key="repair_proof",
        )
        reasoning_text = reviewer_reasoning
        if len(reasoning_text) > max(3_000, self.prompt_budgets.proof_compilation // 6):
            reasoning_text = self._truncate_for_budget(
                reasoning_text,
                max(3_000, self.prompt_budgets.proof_compilation // 6),
            )
        return repair_proof, reasoning_text

    def _assemble_falsifier_input(self, complete_proof: str) -> AssemblyResult:
        synopsis = self._truncate_for_budget(complete_proof, min(6_000, max(2_000, len(complete_proof) // 3)))
        result = self.assembler.fit(
            [
                PromptSection(
                    name="proof",
                    priority=4,
                    variants=[
                        PromptVariant("full", complete_proof),
                        PromptVariant(
                            "compact",
                            self._truncate_for_budget(
                                complete_proof,
                                min(self.prompt_budgets.falsifier, max(6_000, len(complete_proof) // 2)),
                            ),
                        ),
                        PromptVariant("synopsis", synopsis),
                    ],
                ),
            ],
            builder=lambda selected: selected.get("proof", ""),
            max_chars=self.prompt_budgets.falsifier,
            degrade_bias=self._assembly_bias.get("falsifier", 0),
        )
        self._update_assembly_bias("falsifier", result)
        return result

    def _assemble_notes_for_compile(self) -> AssemblyResult:
        state = self.memo.load()
        current = self.notes.render_for_compile(
            current_roadmap=self._roadmaps_attempted,
            current_roadmap_id=state.current_roadmap_id or None,
            max_chars=self.prompt_budgets.proof_compilation,
        )
        compact = self.notes.render_for_compile(
            current_roadmap=self._roadmaps_attempted,
            current_roadmap_id=state.current_roadmap_id or None,
            keep_recent_roadmaps=1,
            max_chars=max(20_000, self.prompt_budgets.proof_compilation // 2),
        )
        newest = self.notes.render_for_worker(
            relevant_keys=None,
            max_chars=max(12_000, self.prompt_budgets.proof_compilation // 4),
        )
        result = self.assembler.fit(
            [
                PromptSection(
                    name="notes",
                    priority=4,
                    variants=[
                        PromptVariant("full", current),
                        PromptVariant("compact", compact),
                        PromptVariant("recent_only", newest),
                    ],
                ),
            ],
            builder=lambda selected: selected.get("notes", ""),
            max_chars=self.prompt_budgets.proof_compilation,
            degrade_bias=self._assembly_bias.get("proof_compilation", 0),
        )
        self._update_assembly_bias("proof_compilation", result)
        return result

    def _sync_macro_roadmap(self, macro_steps: list[MacroStep] | None) -> None:
        """Persist macro-step status updates back to MEMO."""
        if not macro_steps:
            return
        state = self.memo.load()
        for macro in macro_steps:
            macro.update_status()
        self.memo.set_macro_roadmap(
            macro_steps,
            roadmap_id=state.current_roadmap_id or None,
            approach=state.current_approach or None,
        )

    def _select_interrupting_lemma(
        self,
        current_step_index: int,
    ) -> tuple[int, AuxiliaryLemma] | None:
        """Pick a high-priority lemma that should interrupt the main roadmap."""
        state = self.memo.load()
        for index, lemma in enumerate(state.lemma_queue):
            if lemma.status != "pending":
                continue
            if lemma.unblocks and current_step_index not in lemma.unblocks:
                continue
            return index, lemma
        return None

    async def _verify_resumed_step(
        self, step: RoadmapStep
    ) -> bool:
        """Verify a single PROVED step during resume. Emits events.

        Returns True if the recorded proof checks out, False otherwise.
        """
        # Try in-MEMO proof_text first, then prop_id-keyed NOTES heading,
        # then legacy Step-N heading (backward compat with old NOTES).
        proof_text = step.proof_text
        if not proof_text and step.lemma_dependencies:
            proof_text = self.notes.get_proposition_proof(
                step.lemma_dependencies[0]
            )
        if not proof_text:
            proof_text = self.notes.get_step_proof(step.step_index, step_id=step.step_id)
        if not proof_text:
            proof_text = self.notes.get_step_proof(step.step_index)
        if not proof_text:
            logger.warning(
                "No proof found in NOTES for step %d, marking invalid.",
                step.step_index,
            )
            self._emit(
                ThinkingEvent(
                    "resume_verify_failed",
                    step_index=step.step_index,
                    content=f"Step {step.step_index}: no proof record found. Will re-prove.",
                )
            )
            return False

        verified = await self.thinking.verify_proved_step(
            self.problem,
            step.description,
            step.step_index,
            proof_text,
        )
        if verified:
            self._emit(
                ThinkingEvent(
                    "resume_verify_passed",
                    step_index=step.step_index,
                    content=f"Step {step.step_index}: verified correct. Skipping.",
                )
            )
            logger.info("Step %d verified correct.", step.step_index)
            return True

        self._emit(
            ThinkingEvent(
                "resume_verify_failed",
                step_index=step.step_index,
                content=f"Step {step.step_index}: verification failed. Will re-prove from here.",
            )
        )
        logger.warning("Step %d failed verification.", step.step_index)
        return False

    async def _try_resume_from_memo_state(self, memo_state: MemoState) -> bool:
        """Try to resume from an in-progress roadmap in MEMO.

        Two cases are handled:

        - **Partial roadmap** (some PROVED, some UNPROVED): verify the
          proved steps, then resume at the first unproved step. This is
          the classic "pick up where we left off" resume.
        - **All-PROVED roadmap**: the previous run finished the work
          phase but crashed at (or before) review / falsifier. Verify
          the proofs and resume straight into the review-and-repair
          loop rather than throwing the completed roadmap away. Without
          this branch, the resumed run regenerates the roadmap from
          scratch and can invoke review-rejected lemmas all over again.

        In both cases, if a step's recorded proof fails verification,
        that step and all downstream steps are demoted to UNPROVED so
        the main loop re-proves them; we still resume from the existing
        roadmap rather than regenerating.

        Returns ``True`` if ``run()`` should use the MEMO's current
        roadmap on its first while-iteration instead of generating a
        fresh one, ``False`` otherwise.
        """
        if not memo_state.current_roadmap:
            return False

        proved_steps = [
            s for s in memo_state.current_roadmap if s.status == "PROVED"
        ]
        unproved_steps = [
            s
            for s in memo_state.current_roadmap
            if s.status in ("UNPROVED", "IN_PROGRESS")
        ]

        if not proved_steps:
            return False  # nothing to verify → normal generate path

        if unproved_steps:
            resume_mode = "partial"
            resume_banner = (
                f"Resuming from previous run: {len(proved_steps)} proved, "
                f"{len(unproved_steps)} remaining. Verifying proved steps..."
            )
            resume_log = (
                "Found in-progress roadmap: %d proved, %d remaining. "
                "Verifying proved steps..."
            )
            logger.info(resume_log, len(proved_steps), len(unproved_steps))
        else:
            resume_mode = "all_proved"
            resume_banner = (
                f"Resuming all-PROVED roadmap: {len(proved_steps)} steps. "
                "Verifying before review..."
            )
            logger.info(
                "Found all-PROVED roadmap (%d steps). Verifying before review...",
                len(proved_steps),
            )

        self._emit(
            ThinkingEvent(
                "resume_verify",
                content=resume_banner,
                metadata={
                    "resume_mode": resume_mode,
                    "current_roadmap": [
                        {
                            "step_index": s.step_index,
                            "description": s.description,
                            "status": s.status,
                        }
                        for s in memo_state.current_roadmap
                    ],
                },
            )
        )

        all_valid = True
        first_invalid_index: int | None = None
        for step in proved_steps:
            if await self._verify_resumed_step(step):
                continue
            all_valid = False
            first_invalid_index = step.step_index
            break

        if all_valid:
            self._inject_structured_premises(memo_state.current_roadmap)
            if resume_mode == "partial":
                ready_msg = (
                    f"All {len(proved_steps)} proved steps verified. "
                    f"Resuming from step {unproved_steps[0].step_index}."
                )
            else:
                ready_msg = (
                    f"All {len(proved_steps)} proved steps verified. "
                    "Resuming into review-and-repair loop."
                )
            self._emit(ThinkingEvent("resume_ready", content=ready_msg))
            return True

        assert first_invalid_index is not None
        for step in memo_state.current_roadmap:
            if step.step_index >= first_invalid_index:
                step.status = "UNPROVED"
                step.result = None
        if memo_state.macro_roadmap:
            self._sync_macro_roadmap(memo_state.macro_roadmap)
        else:
            self.memo.set_current_roadmap(
                memo_state.current_roadmap,
                roadmap_id=getattr(memo_state, "current_roadmap_id", "") or None,
                approach=getattr(memo_state, "current_approach", "") or None,
            )
        self._emit(
            ThinkingEvent(
                "resume_ready",
                content=(
                    f"Step {first_invalid_index} failed verification. "
                    f"Resuming from step {first_invalid_index}."
                ),
            )
        )
        return True

    async def run(self) -> Phase1Result:
        """Run Phase 1 to completion."""
        max_roadmap_attempts = 5  # safety limit

        # --- Fix 4: cross-session proposition quarantine ---
        # Before we do anything else, scrub the MEMO for review-rejected
        # or orphan propositions that leaked across from a prior run. If
        # the current process is resuming from a MEMO.json written by an
        # earlier session, any ProvedProposition whose origin roadmap was
        # review-rejected is in the "trusted" bucket because the prior
        # session's in-session archive_roadmap() couldn't see it. Left
        # alone, the next planner would cite those as premises again.
        try:
            quarantined = self.memo.quarantine_cross_session_propositions()
        except Exception:  # pragma: no cover — defensive
            quarantined = 0
        if quarantined:
            self._emit(
                ThinkingEvent(
                    "cross_session_quarantine",
                    content=(
                        f"Flagged {quarantined} cross-session proposition(s) "
                        "as suspect (review-rejected or orphan origin)."
                    ),
                    metadata={"count": quarantined},
                )
            )

        # Check if there's a handoff from a previous context reset
        memo_state = self._sanitize_resume_macro_state(self.memo.load())
        if memo_state.handoff:
            handoff_message = self._handoff_context_message(memo_state.handoff)
            self.thinking.add_to_context(
                RuntimeMessage(role="user", content=handoff_message)
            )
            self._emit(
                ThinkingEvent(
                    "handoff",
                    content=(
                        f"Resuming from handoff: {memo_state.handoff.next_action}. "
                        f"Strategy: {memo_state.handoff.current_strategy}. "
                        f"Confidence: {memo_state.handoff.confidence:.2f}."
                    ),
                    metadata={
                        "next_action": memo_state.handoff.next_action,
                        "open_questions": memo_state.handoff.open_questions,
                        "blockers": memo_state.handoff.blockers,
                        "proved_steps": memo_state.handoff.proved_steps,
                        "remaining_steps": memo_state.handoff.remaining_steps,
                        "reusable_prop_ids": memo_state.handoff.reusable_prop_ids,
                    },
                )
            )
            self._emit(
                ThinkingEvent(
                    "handoff_loaded",
                    content="Loaded structured handoff into the fresh thinking context.",
                    metadata={
                        "roadmap_number": memo_state.handoff.roadmap_number,
                        "current_step_index": memo_state.handoff.current_step_index,
                    },
                )
            )
            # Clear the handoff after consuming it
            self.memo.clear_handoff()
            if memo_state.current_roadmap:
                self._inject_structured_premises(memo_state.current_roadmap)

        # --- Resume from in-progress roadmap ---
        resumed_from_progress = await self._try_resume_from_memo_state(memo_state)

        while self._roadmaps_attempted < max_roadmap_attempts:
            self._roadmaps_attempted += 1
            self.detector.reset()

            # --- Pre-roadmap dedup: remove duplicate propositions ---
            try:
                removed_ids = self.memo.deduplicate_propositions()
                if removed_ids:
                    self.notes.remove_sections(removed_ids)
                    self._emit(
                        ThinkingEvent(
                            "dedup_cleanup",
                            content=(
                                f"Removed {len(removed_ids)} duplicate proposition(s) "
                                f"before roadmap generation: "
                                f"{', '.join(removed_ids)}"
                            ),
                            metadata={"removed_prop_ids": removed_ids},
                        )
                    )
            except Exception:
                logger.debug("Pre-roadmap dedup failed; continuing.", exc_info=True)

            # --- Resume: use the in-progress roadmap on first iteration ---
            if resumed_from_progress:
                resumed_from_progress = False  # only on first iteration
                memo_state = self._sanitize_resume_macro_state(self.memo.load())
                steps = memo_state.current_roadmap
                macro_steps = memo_state.macro_roadmap
                self._annotate_step_obligations(steps)
                roadmap_id = memo_state.current_roadmap_id or self._roadmap_id_for_attempt(self._roadmaps_attempted)
                self._assign_step_identity(steps, roadmap_id=roadmap_id)
                # Reconstruct approach from step descriptions
                chosen = {
                    "approach": (
                        self._resume_approach
                        or memo_state.current_approach
                        or "Resumed from previous run"
                    ),
                    "steps": [s.description for s in steps],
                }
                self._emit(
                    ThinkingEvent(
                        "roadmap_generated",
                        content="Resumed roadmap from previous run.",
                        metadata={
                            "steps": [s.description for s in steps],
                            "count_considered": 0,
                            "runner_up_used": False,
                            "resumed": True,
                            **self._current_roadmap_payload(steps, macro_steps),
                        },
                    )
                )
            else:
                # --- Normal Roadmap Generation ---
                memo_state = self._sanitize_resume_macro_state(self.memo.load())
                planner_memory = self._assemble_planner_memory()
                memo_content = planner_memory.text or None

                is_first = self._roadmaps_attempted == 1 and memo_content is None

                # --- P4: Try runner-up roadmap before generating fresh ---
                chosen = None
                runner_up_used = False

                if not is_first and memo_state.runner_up_roadmaps:
                    # Try the best runner-up instead of generating fresh
                    runner_up = self.memo.pop_runner_up()
                    if runner_up:
                        chosen = {
                            "approach": runner_up.approach,
                            "steps": runner_up.steps,
                            "step_obligations": runner_up.step_obligations,
                            "macro_steps": runner_up.macro_steps,
                            "reasoning": runner_up.reasoning,
                        }
                        runner_up_used = True
                        logger.info(
                            "Using runner-up roadmap: %s",
                            runner_up.approach[:80],
                        )

                if chosen is None:
                    # Generate fresh roadmaps
                    count = 3 if is_first else 1
                    # Fix 5: feed prior abandoned attempts to the planner
                    # so the divergence instruction fires when 2+ attempts
                    # have already been thrown away.
                    try:
                        prior_attempts = self.memo.prior_attempts_summary()
                    except Exception:  # pragma: no cover — defensive
                        prior_attempts = []
                    try:
                        roadmaps = await self.thinking.generate_roadmaps(
                            self.problem,
                            memo_content,
                            count=count,
                            prior_attempts=prior_attempts or None,
                            extra_metadata={
                                "assembly_profile": planner_memory.profile,
                                "document_char_counts": {
                                    "memo_content": len(memo_content or ""),
                                    **planner_memory.section_char_counts,
                                },
                            },
                        )
                    except InputTooLargeError as exc:
                        # Defensive fallback: the prompt assembler should
                        # already have degraded planner memory aggressively.
                        logger.warning(
                            "Prompt too large (%s chars); retrying without planner memory.",
                            f"{exc.actual:,}",
                        )
                        self._emit(
                            ThinkingEvent(
                                "compression",
                                content=(
                                    f"Prompt too large ({exc.actual:,} chars). "
                                    f"Retrying roadmap generation without planner memory."
                                ),
                                metadata={
                                    "assembly_profile": planner_memory.profile,
                                    "section_char_counts": planner_memory.section_char_counts,
                                },
                            )
                        )
                        roadmaps = await self.thinking.generate_roadmaps(
                            self.problem,
                            None,
                            count=1,
                            prior_attempts=prior_attempts or None,
                            extra_metadata={
                                "assembly_profile": "planner_memory:none",
                                "document_char_counts": {},
                            },
                        )

                    if not roadmaps:
                        self._emit(
                            ThinkingEvent(
                                "abandoned", content="Failed to generate any roadmap."
                            )
                        )
                        continue

                    chosen = roadmaps[0]

                    # P4: Store runner-ups on first attempt (when 3 were generated)
                    if is_first and len(roadmaps) > 1:
                        self.memo.store_runner_ups(roadmaps[1:])
                        logger.info(
                            "Stored %d runner-up roadmap(s) for fallback.",
                            len(roadmaps) - 1,
                        )

                roadmap_id = self._roadmap_id_for_attempt(self._roadmaps_attempted)
                macro_steps = self._macro_steps_from_choice(chosen)
                if macro_steps:
                    steps = self._flatten_macro_steps(macro_steps)
                else:
                    steps = [
                        RoadmapStep(
                            step_index=i + 1,
                            description=desc,
                            status="UNPROVED",
                            roadmap_id=roadmap_id,
                            step_id=f"{roadmap_id}:step:{i + 1}",
                            downstream_obligations=self._choice_step_obligations(chosen, i),
                        )
                        for i, desc in enumerate(
                            chosen.get("steps", [])[: self.hyper.n_max]
                        )
                    ]

                if not steps:
                    self._emit(
                        ThinkingEvent("abandoned", content="Roadmap had no steps.")
                    )
                    continue

                self._annotate_step_obligations(steps)
                self._assign_step_identity(steps, roadmap_id=roadmap_id)
                if macro_steps:
                    self.memo.set_macro_roadmap(
                        macro_steps,
                        roadmap_id=roadmap_id,
                        approach=chosen.get("approach", ""),
                    )
                else:
                    self.memo.set_current_roadmap(
                        steps,
                        roadmap_id=roadmap_id,
                        approach=chosen.get("approach", ""),
                    )
                self._resume_approach = chosen.get("approach", "") or None
                self.memo.record_generated_strategy(
                    f"Roadmap {self._roadmaps_attempted}",
                    chosen.get("approach", ""),
                    steps,
                    roadmap_id=roadmap_id,
                )

                self._emit(
                    ThinkingEvent(
                        "roadmap_generated",
                        content=chosen.get("approach", ""),
                        metadata={
                            "steps": [s.description for s in steps],
                            "count_considered": 1 if runner_up_used else (3 if is_first else 1),
                            "runner_up_used": runner_up_used,
                            "assembly_profile": planner_memory.profile,
                            "planner_section_char_counts": planner_memory.section_char_counts,
                            **self._current_roadmap_payload(steps, macro_steps),
                        },
                    )
                )

            # --- P2: Lean statement check after roadmap selection ---
            if self.toolplane is not None and not any(s.status == "PROVED" for s in steps):
                try:
                    formalizer = self.formalizer or self.thinking
                    stmt = await formalizer.formalize_statement(
                        self.problem, chosen.get("approach", ""),
                    )
                    if stmt:
                        self.memo.upsert_formal_artifact(
                            claim=f"Theorem statement: {chosen.get('approach', 'roadmap')}",
                            claim_status="conjectured",
                            debt_label="temporary_hole",
                            lean_statement=stmt,
                        )
                        stmt_result = await self.toolplane.check_statement(stmt)
                        lean_ok = stmt_result and stmt_result.success
                        if lean_ok:
                            self.memo.upsert_formal_artifact(
                                claim=f"Theorem statement: {chosen.get('approach', 'roadmap')}",
                                claim_status="lean_statement_checked",
                                debt_label="none",
                                lean_statement=stmt,
                            )
                        self._emit(
                            ThinkingEvent(
                                "lean_statement_check",
                                content=f"Lean statement check: {'ok' if lean_ok else 'FAILED'}",
                                metadata={"lean_ok": lean_ok, "statement": stmt[:200]},
                            )
                        )
                        if not lean_ok:
                            detail = "Lean statement check failed."
                            if stmt_result and stmt_result.errors:
                                detail += " " + " | ".join(
                                    err.message for err in stmt_result.errors[:3]
                                )
                            self.memo.archive_roadmap(
                                f"Roadmap {self._roadmaps_attempted}",
                                chosen.get("approach", ""),
                                detail,
                                [],
                                detail,
                                roadmap_id=roadmap_id,
                            )
                            continue
                except Exception as e:
                    logger.warning("Lean statement check error: %s", e)

            # --- Execution Loop ---
            roadmap_summary = self._build_roadmap_summary(
                chosen.get("approach", ""),
                steps,
                macro_steps,
            )
            required_obligations = self._format_required_obligations(
                self._required_obligation_keys(self.problem)
            )
            iteration = 0

            diagnosed_failures: list[StepFailure] = []
            roadmap_archived = False

            execution_macros = macro_steps or [
                MacroStep(
                    index=1,
                    description="Main roadmap",
                    deliverable=chosen.get("approach", "") or "Complete proof",
                    sub_steps=steps,
                )
            ]

            for macro in execution_macros:
                macro.update_status()
                rerun_macro = True
                while rerun_macro:
                    rerun_macro = False
                    roadmap_summary = self._build_roadmap_summary(
                        chosen.get("approach", ""),
                        steps,
                        macro_steps,
                        active_macro=macro if macro_steps else None,
                    )
                    for step in macro.sub_steps:
                        if step.status == "PROVED":
                            logger.info(
                                "Skipping step %d (already proved).", step.step_index
                            )
                            continue

                        interrupting_lemma = self._select_interrupting_lemma(
                            step.step_index
                        )
                        if interrupting_lemma is not None:
                            lemma_index, lemma = interrupting_lemma
                            lemma_result = await self.thinking.work_step(
                                self.problem,
                                roadmap_summary,
                                lemma.statement,
                                step.step_index,
                                context_notes=self._structured_premises_text(steps),
                            )
                            if lemma_result.verification_passed:
                                self.memo.resolve_lemma(lemma_index)
                                lemma_prop = await self.assistant.extract_proved_proposition(
                                    lemma_result
                                )
                                if lemma_prop:
                                    prop_id, statement = lemma_prop
                                    self.memo.add_proved_proposition(
                                        prop_id,
                                        statement,
                                        f"Lemma queue, step {step.step_index}",
                                        source_roadmap_id=step.roadmap_id,
                                        source_step_id=step.step_id,
                                    )
                                self._emit(
                                    ThinkingEvent(
                                        "lemma_resolved",
                                        step_index=step.step_index,
                                        content=(
                                            f"Resolved pending {lemma.lemma_type} lemma "
                                            f"before step {step.step_index}."
                                        ),
                                    )
                                )

                        proved = False
                        redo_count = 0
                        max_redos = 3
                        step_error_reasons: list[str] = []
                        repair_feedback = ""

                        while not proved and redo_count < max_redos:
                            iteration += 1
                            redo_count += 1

                            self._emit(
                                ThinkingEvent(
                                    "step_started",
                                    step_index=step.step_index,
                                    content=f"Working on step {step.step_index}: {step.description}",
                                    metadata=self._current_roadmap_payload(
                                        steps, macro_steps
                                    ),
                                )
                            )

                            worker_context = self._assemble_worker_context(
                                steps=steps,
                                step=step,
                                repair_feedback=repair_feedback,
                            )
                            context_notes = worker_context.text

                            result = await self.thinking.work_step(
                                self.problem,
                                roadmap_summary,
                                step.description,
                                step.step_index,
                                context_notes=context_notes,
                                extra_metadata={
                                    "assembly_profile": worker_context.profile,
                                    "document_char_counts": worker_context.section_char_counts,
                                },
                            )

                            if result.status == "PROVED" and result.verification_passed:
                                step.claim = step.description
                                step.proof_text = result.proof_detail
                                step.verification_result = result.verification_outcome
                                self.memo.upsert_formal_artifact(
                                    claim=step.claim,
                                    proof_text=result.proof_detail,
                                    claim_status="informally_justified",
                                    debt_label="temporary_hole",
                                )

                                sketch_feedback = ""
                                if self.toolplane is not None:
                                    try:
                                        formalizer = self.formalizer or self.thinking
                                        sketch = await formalizer.formalize_step_sketch(
                                            self.problem,
                                            step.description,
                                            [
                                                p.statement
                                                for p in self.memo.load().proved_propositions
                                            ],
                                        )
                                        if sketch:
                                            self.memo.upsert_formal_artifact(
                                                claim=step.claim,
                                                proof_text=result.proof_detail,
                                                claim_status="informally_justified",
                                                debt_label="temporary_hole",
                                                lean_sketch=sketch,
                                            )
                                            sketch_result = await self.toolplane.check_sketch(
                                                sketch
                                            )
                                            if sketch_result and sketch_result.success:
                                                step.lean_status = "sketch_ok"
                                                self.memo.upsert_formal_artifact(
                                                    claim=step.claim,
                                                    proof_text=result.proof_detail,
                                                    claim_status="lean_sketch_checked",
                                                    debt_label="none",
                                                    lean_sketch=sketch,
                                                )
                                            else:
                                                step.lean_status = "sketch_failed"
                                                if sketch_result and sketch_result.errors:
                                                    sketch_feedback = "Lean sketch failed:\n" + "\n".join(
                                                        f"- {err.message}"
                                                        for err in sketch_result.errors[:3]
                                                    )
                                                else:
                                                    sketch_feedback = (
                                                        "Lean sketch failed to type-check."
                                                    )
                                            self._emit(
                                                ThinkingEvent(
                                                    "lean_sketch_check",
                                                    step_index=step.step_index,
                                                    content=f"Lean sketch check: {step.lean_status}",
                                                    metadata={
                                                        "lean_status": step.lean_status
                                                    },
                                                )
                                            )
                                    except Exception as e:
                                        logger.warning("Lean sketch check failed: %s", e)

                                if sketch_feedback and redo_count < max_redos:
                                    repair_feedback = (
                                        sketch_feedback
                                        + "\n\nRepair the mathematical step so it can be formalized."
                                    )
                                    step_error_reasons.append(sketch_feedback)
                                    self._emit(
                                        ThinkingEvent(
                                            "gap_repair",
                                            step_index=step.step_index,
                                            content=(
                                                f"Repairing step {step.step_index} after Lean sketch failure."
                                            ),
                                            metadata={"feedback": sketch_feedback},
                                        )
                                    )
                                    continue

                                proved = True
                                step.status = "PROVED"

                                prop = await self.assistant.extract_proved_proposition(
                                    result
                                )
                                prop_id = ""
                                if prop:
                                    prop_id, statement = prop
                                    self.memo.add_proved_proposition(
                                        prop_id,
                                        statement,
                                        f"Roadmap {self._roadmaps_attempted}, step {step.step_index}",
                                        source_roadmap_id=step.roadmap_id,
                                        source_step_id=step.step_id,
                                    )
                                    step.lemma_dependencies = [prop_id]

                                brief, detail = await self.assistant.summarize_step_for_memo(
                                    step.step_index,
                                    result,
                                )
                                self.memo.append_step_result(
                                    step.step_index,
                                    "PROVED",
                                    brief,
                                )
                                notes_key = (
                                    prop_id
                                    if prop
                                    else step.step_id or f"step_{self._roadmaps_attempted}_{step.step_index}"
                                )
                                note_id = self.notes.append_step_proof(
                                    step.step_index,
                                    step.description,
                                    detail,
                                    key=notes_key,
                                    roadmap_index=self._roadmaps_attempted,
                                    roadmap_id=step.roadmap_id,
                                    roadmap_label=f"Roadmap {self._roadmaps_attempted}",
                                    step_id=step.step_id,
                                    prop_id=prop_id or None,
                                    dependencies=step.lemma_dependencies,
                                )
                                if prop_id:
                                    memo_state = self.memo.load()
                                    for proposition in memo_state.proved_propositions:
                                        if proposition.prop_id == prop_id:
                                            proposition.note_id = note_id
                                            break
                                    self.memo.save(memo_state)

                                if macro_steps:
                                    self._sync_macro_roadmap(macro_steps)
                                    steps = self._flatten_macro_steps(macro_steps)
                                else:
                                    self.memo.set_current_roadmap(
                                        steps,
                                        roadmap_id=roadmap_id,
                                        approach=chosen.get("approach", ""),
                                    )
                                roadmap_summary = self._build_roadmap_summary(
                                    chosen.get("approach", ""),
                                    steps,
                                    macro_steps,
                                    active_macro=macro if macro_steps else None,
                                )

                                self._emit(
                                    ThinkingEvent(
                                        "step_verified",
                                        step_index=step.step_index,
                                        content=f"Step {step.step_index} verified correct.",
                                        metadata={
                                            "worker_assembly_profile": worker_context.profile,
                                            "worker_section_char_counts": worker_context.section_char_counts,
                                            **self._current_roadmap_payload(
                                                steps, macro_steps
                                            ),
                                            "proved_propositions": [
                                                {
                                                    "prop_id": p.prop_id,
                                                    "statement": p.statement,
                                                    "source": p.source,
                                                }
                                                for p in self.memo.load().proved_propositions
                                            ],
                                        },
                                    )
                                )

                                active_scope = macro.sub_steps if macro_steps else steps
                                completed = [
                                    {
                                        "index": s.step_index,
                                        "description": s.description,
                                        "obligations": s.downstream_obligations,
                                    }
                                    for s in active_scope
                                    if s.status == "PROVED"
                                ]
                                remaining = [
                                    {
                                        "index": s.step_index,
                                        "description": s.description,
                                        "obligations": s.downstream_obligations,
                                    }
                                    for s in active_scope
                                    if s.status == "UNPROVED"
                                ]

                                reevaluate_interval = max(2, min(self.hyper.K, 3))
                                should_reevaluate = bool(remaining) and (
                                    len(completed) % reevaluate_interval == 0
                                    or bool(prop)
                                    or (macro_steps is not None and macro.status == "PROVED")
                                    or redo_count > 1
                                )

                                if should_reevaluate:
                                    evaluation = await self.thinking.re_evaluate_roadmap(
                                        self.problem,
                                        roadmap_summary,
                                        completed,
                                        remaining,
                                        required_obligations=required_obligations,
                                    )
                                    if not evaluation.on_track and evaluation.updated_steps:
                                        lost_coverage = self._coverage_losses_from_update(
                                            active_scope,
                                            evaluation.updated_steps,
                                        )
                                        self._apply_updated_steps_to_scope(
                                            active_scope,
                                            evaluation.updated_steps,
                                        )
                                        if lost_coverage:
                                            self._append_steps_for_missing_obligations(
                                                steps=steps,
                                                macro_steps=macro_steps,
                                                missing_obligations=lost_coverage,
                                            )
                                        if evaluation.needs_extension and evaluation.missing_obligations:
                                            remaining_missing = [
                                                key
                                                for key in self._roadmap_coverage(steps)[
                                                    "missing_total"
                                                ]
                                                if key in {
                                                    self._normalize_obligation_key(item)
                                                    for item in evaluation.missing_obligations
                                                }
                                            ]
                                            if remaining_missing:
                                                self._append_steps_for_missing_obligations(
                                                    steps=steps,
                                                    macro_steps=macro_steps,
                                                    missing_obligations=remaining_missing,
                                                )
                                        self._annotate_step_obligations(steps)
                                        if macro_steps:
                                            self._renumber_macro_steps(macro_steps)
                                            self._sync_macro_roadmap(macro_steps)
                                            steps = self._flatten_macro_steps(macro_steps)
                                        else:
                                            steps.sort(key=lambda item: item.step_index)
                                            self.memo.set_current_roadmap(
                                                steps,
                                                roadmap_id=roadmap_id,
                                                approach=chosen.get("approach", ""),
                                            )
                                        roadmap_summary = self._build_roadmap_summary(
                                            chosen.get("approach", ""),
                                            steps,
                                            macro_steps,
                                            active_macro=macro if macro_steps else None,
                                        )
                                        self._emit(
                                            ThinkingEvent(
                                                "roadmap_reevaluated",
                                                content=evaluation.reasoning,
                                                metadata={
                                                    "trigger": (
                                                        "cadence"
                                                        if len(completed) % reevaluate_interval == 0
                                                        else "structural_event"
                                                    ),
                                                    "missing_obligations": evaluation.missing_obligations,
                                                    "needs_extension": evaluation.needs_extension,
                                                    "coverage_losses": lost_coverage,
                                                },
                                            )
                                        )
                                    elif (
                                        not evaluation.on_track
                                        and evaluation.needs_extension
                                        and evaluation.missing_obligations
                                    ):
                                        appended = self._append_steps_for_missing_obligations(
                                            steps=steps,
                                            macro_steps=macro_steps,
                                            missing_obligations=evaluation.missing_obligations,
                                        )
                                        if appended:
                                            roadmap_summary = self._build_roadmap_summary(
                                                chosen.get("approach", ""),
                                                steps,
                                                macro_steps,
                                                active_macro=macro if macro_steps else None,
                                            )
                                            self._emit(
                                                ThinkingEvent(
                                                    "roadmap_extended",
                                                    content=evaluation.reasoning,
                                                    metadata={
                                                        "trigger": "reevaluate_extension",
                                                        "missing_obligations": evaluation.missing_obligations,
                                                        "added_steps": appended,
                                                    },
                                                )
                                            )
                            else:
                                step_error_reasons.append(
                                    result.error_reason or result.verification_notes
                                )
                                self._emit(
                                    ThinkingEvent(
                                        "step_failed",
                                        step_index=step.step_index,
                                        content=(
                                            f"{result.status} (attempt {redo_count}/{max_redos}): "
                                            f"{result.error_reason or result.verification_notes}"
                                        ),
                                        metadata={
                                            **self._current_roadmap_payload(
                                                steps, macro_steps
                                            ),
                                            "verification_outcome": result.verification_outcome,
                                            "false_claim": result.false_claim,
                                            "derived_claim": result.derived_claim,
                                        },
                                    )
                                )
                                if result.verification_outcome == "REFUTED_STEP":
                                    redo_count = max_redos
                                    break

                            total_proved = sum(
                                1 for s in steps if s.status == "PROVED"
                            )
                            self.detector.record(
                                ProgressEntry(
                                    iteration=iteration,
                                    steps_proved=total_proved,
                                    new_insights=proved,
                                    step_status_changed=proved,
                                )
                            )

                            messages, was_reset = await self.compressor.compress_if_needed(
                                self.thinking.context,
                            )
                            if was_reset:
                                handoff = self._build_handoff(
                                    steps, step, roadmap_summary,
                                )
                                self.memo.set_handoff(handoff)
                                self.thinking.clear_context()
                                self.thinking.add_to_context(
                                    RuntimeMessage(
                                        role="user",
                                        content=self._handoff_context_message(handoff),
                                    )
                                )
                                self._inject_structured_premises(steps)
                                self._emit(
                                    ThinkingEvent(
                                        "handoff",
                                        content=(
                                            f"Context reset with handoff. "
                                            f"Next: {handoff.next_action}. "
                                            f"Open questions: {len(handoff.open_questions)}."
                                        ),
                                        metadata={
                                            "next_action": handoff.next_action,
                                            "open_questions": handoff.open_questions,
                                            "blockers": handoff.blockers,
                                            "confidence": handoff.confidence,
                                            "proved_steps": handoff.proved_steps,
                                            "remaining_steps": handoff.remaining_steps,
                                            "proof_keys": handoff.proof_keys,
                                        },
                                    )
                                )
                                self._emit(
                                    ThinkingEvent(
                                        "handoff_loaded",
                                        content="Re-seeded fresh context from deterministic handoff.",
                                        metadata={
                                            "roadmap_number": handoff.roadmap_number,
                                            "current_step_index": handoff.current_step_index,
                                        },
                                    )
                                )
                            elif messages != self.thinking.context:
                                self.thinking._context = messages
                                # Local context was mutated (truncate/snip/
                                # summarize). The CLI's resumable session
                                # still mirrors the *uncompressed* chat, so
                                # drop the session id to force a fresh
                                # command that re-embeds the compressed
                                # transcript on the next invoke.
                                self.thinking.runtime.invalidate_session()
                                self._emit(
                                    ThinkingEvent(
                                        "compression",
                                        content=(
                                            f"Compressed context "
                                            f"({self.compressor.events[-1].action})."
                                        ),
                                    )
                                )

                        if proved:
                            continue

                        step.status = "FAILED"
                        step.proof_text = result.proof_detail
                        step.verification_result = result.verification_outcome
                        self.memo.upsert_formal_artifact(
                            claim=step.claim or step.description,
                            proof_text=step.proof_text,
                            claim_status=(
                                "informally_justified"
                                if step.proof_text
                                else "conjectured"
                            ),
                            debt_label="temporary_hole",
                            dependencies=step.lemma_dependencies,
                        )

                        if result.verification_outcome == "REFUTED_STEP":
                            diagnosis = {
                                "diagnosis": "FALSE_PROPOSITION",
                                "explanation": (
                                    result.verification_notes
                                    or "The verifier determined this step is false as stated."
                                ),
                                "false_claim": result.false_claim or step.description,
                            }
                        elif result.verification_outcome == "PROVED_DIFFERENT_CLAIM":
                            diagnosis = {
                                "diagnosis": "LOGICAL_GAP",
                                "explanation": (
                                    result.verification_notes
                                    or "The proof established a different claim than the requested step."
                                ),
                                "false_claim": "",
                            }
                        else:
                            diagnosis = await self.thinking.diagnose_step_failure(
                                self.problem,
                                step.description,
                                step.step_index,
                                step_error_reasons,
                            )

                        step_failure = StepFailure(
                            step_index=step.step_index,
                            description=step.description,
                            diagnosis=diagnosis["diagnosis"],
                            explanation=diagnosis["explanation"],
                            false_claim=diagnosis.get("false_claim", ""),
                        )
                        diagnosed_failures.append(step_failure)

                        if (
                            step_failure.diagnosis == "FALSE_PROPOSITION"
                            and step_failure.false_claim
                        ):
                            self.memo.add_refuted_proposition(step_failure)

                        failure_detail = (
                            f"[{diagnosis['diagnosis']}] {diagnosis['explanation']}"
                        )
                        if diagnosis.get("false_claim"):
                            failure_detail += (
                                f" FALSE CLAIM: {diagnosis['false_claim']}"
                            )

                        self.memo.append_step_result(
                            step.step_index,
                            "FAILED",
                            failure_detail,
                        )

                        self._emit(
                            ThinkingEvent(
                                "step_diagnosed",
                                step_index=step.step_index,
                                content=(
                                    f"Step {step.step_index} failure diagnosis: "
                                    f"{failure_detail}"
                                ),
                                metadata={
                                    "diagnosis": diagnosis["diagnosis"],
                                    "explanation": diagnosis["explanation"],
                                    "false_claim": diagnosis.get("false_claim", ""),
                                },
                            )
                        )

                        active_scope = macro.sub_steps if macro_steps else steps
                        remaining_after = [
                            {"index": s.step_index, "description": s.description}
                            for s in active_scope
                            if s.status == "UNPROVED"
                        ]
                        if remaining_after:
                            completed_so_far = [
                                {"index": s.step_index, "description": s.description}
                                for s in active_scope
                                if s.status == "PROVED"
                            ]
                            failed_info = {
                                "index": step.step_index,
                                "description": step.description,
                            }
                            failure_eval = await self.thinking.re_evaluate_after_failure(
                                self.problem,
                                roadmap_summary,
                                completed_so_far,
                                failed_info,
                                remaining_after,
                            )

                            self._emit(
                                ThinkingEvent(
                                    "roadmap_reevaluated",
                                    step_index=step.step_index,
                                    content=(
                                        f"After step {step.step_index} FAILED: "
                                        f"{failure_eval.reasoning}"
                                    ),
                                    metadata={
                                        "should_abandon": failure_eval.should_abandon,
                                        "trigger": "step_failed",
                                        "failed_step": step.step_index,
                                    },
                                )
                            )

                            if failure_eval.should_abandon and macro_steps:
                                regenerated = await self.thinking.regenerate_macro_step(
                                    self.problem,
                                    macro.description,
                                    macro.deliverable,
                                    [
                                        m.deliverable
                                        for m in execution_macros
                                        if m.index < macro.index and m.status == "PROVED"
                                    ],
                                    [
                                        s.description
                                        for s in macro.sub_steps
                                        if s.status != "PROVED"
                                    ],
                                )
                                if regenerated:
                                    preserved = [
                                        s for s in macro.sub_steps if s.status == "PROVED"
                                    ]
                                    macro.sub_steps = preserved + [
                                        RoadmapStep(
                                            step_index=0,
                                            description=desc,
                                            status="UNPROVED",
                                            roadmap_id=roadmap_id,
                                        )
                                        for desc in regenerated
                                    ]
                                    self._renumber_macro_steps(macro_steps)
                                    self._assign_step_identity(
                                        self._flatten_macro_steps(macro_steps),
                                        roadmap_id=roadmap_id,
                                    )
                                    self._sync_macro_roadmap(macro_steps)
                                    steps = self._flatten_macro_steps(macro_steps)
                                    rerun_macro = True
                                    break
                            elif failure_eval.should_abandon:
                                total_proved = sum(
                                    1 for s in steps if s.status == "PROVED"
                                )
                                achieved = [
                                    p.prop_id
                                    for p in self.memo.load().proved_propositions
                                ]
                                self.memo.archive_roadmap(
                                    f"Roadmap {self._roadmaps_attempted}",
                                    chosen.get("approach", ""),
                                    (
                                        f"Step {step.step_index} failed and was critical. "
                                        f"{total_proved}/{len(steps)} steps proved."
                                    ),
                                    achieved,
                                    f"Critical step {step.step_index} failed: {step.description}",
                                    failed_steps=diagnosed_failures,
                                    roadmap_id=roadmap_id,
                                )
                                self.memo.store_runner_ups([])
                                roadmap_archived = True
                                break
                            elif failure_eval.updated_steps:
                                lost_coverage = self._coverage_losses_from_update(
                                    active_scope,
                                    failure_eval.updated_steps,
                                )
                                self._apply_updated_steps_to_scope(
                                    active_scope,
                                    failure_eval.updated_steps,
                                )
                                if lost_coverage:
                                    self._append_steps_for_missing_obligations(
                                        steps=steps,
                                        macro_steps=macro_steps,
                                        missing_obligations=lost_coverage,
                                    )
                                self._annotate_step_obligations(steps)
                                if macro_steps:
                                    self._renumber_macro_steps(macro_steps)
                                    self._sync_macro_roadmap(macro_steps)
                                    steps = self._flatten_macro_steps(macro_steps)
                                else:
                                    steps.sort(key=lambda item: item.step_index)
                                    self.memo.set_current_roadmap(
                                        steps,
                                        roadmap_id=roadmap_id,
                                        approach=chosen.get("approach", ""),
                                    )
                                roadmap_summary = self._build_roadmap_summary(
                                    chosen.get("approach", ""),
                                    steps,
                                    macro_steps,
                                    active_macro=macro if macro_steps else None,
                                )

                        if self.detector.should_abandon():
                            stagnation_summary = self.detector.progress_summary()
                            self._emit(
                                ThinkingEvent(
                                    "abandoned",
                                    content=stagnation_summary,
                                )
                            )
                            total_proved = sum(
                                1 for s in steps if s.status == "PROVED"
                            )
                            achieved = [
                                p.prop_id
                                for p in self.memo.load().proved_propositions
                            ]
                            self.memo.record_stagnation(
                                self._roadmaps_attempted,
                                roadmap_id=roadmap_id,
                                summary=stagnation_summary,
                            )
                            self.memo.archive_roadmap(
                                f"Roadmap {self._roadmaps_attempted}",
                                chosen.get("approach", ""),
                                (
                                    f"No progress after {iteration} iterations. "
                                    f"{total_proved}/{len(steps)} steps proved."
                                ),
                                achieved,
                                stagnation_summary,
                                failed_steps=diagnosed_failures,
                                roadmap_id=roadmap_id,
                            )
                            self.memo.store_runner_ups([])
                            roadmap_archived = True
                            break

                    if roadmap_archived:
                        break
                if roadmap_archived:
                    break

            # Check if all steps proved
            all_proved = all(s.status == "PROVED" for s in steps)

            if not all_proved:
                if roadmap_archived:
                    continue
                # Archive and try new roadmap
                total_proved = sum(
                    1 for s in steps if s.status == "PROVED"
                )
                achieved = [
                    p.prop_id
                    for p in self.memo.load().proved_propositions
                ]
                if not self.detector.should_abandon():  # don't double-archive
                    # Build lesson from diagnosed failures
                    if diagnosed_failures:
                        failure_lessons = "; ".join(
                            f"Step {f.step_index} [{f.diagnosis}]: {f.explanation}"
                            for f in diagnosed_failures
                        )
                    else:
                        failure_lessons = "Some steps could not be proved."

                    self.memo.archive_roadmap(
                        f"Roadmap {self._roadmaps_attempted}",
                        chosen.get("approach", ""),
                        f"{total_proved}/{len(steps)} steps proved. Remaining steps failed.",
                        achieved,
                        failure_lessons,
                        failed_steps=diagnosed_failures,
                        roadmap_id=roadmap_id,
                    )
                    self.memo.store_runner_ups([])
                continue

            completeness_ok, roadmap_summary = await self._ensure_pre_review_completeness(
                approach=chosen.get("approach", ""),
                steps=steps,
                macro_steps=macro_steps,
                roadmap_summary=roadmap_summary,
            )
            if not completeness_ok:
                resumed_from_progress = True
                self._roadmaps_attempted -= 1
                self._resume_approach = chosen.get("approach", "") or self._resume_approach
                continue

            # --- Review + Gap Repair Loop ---
            self._emit(
                ThinkingEvent(
                    "review_started",
                    content="Forking Review Agent for independent evaluation.",
                )
            )

            notes_assembly = self._assemble_notes_for_compile()
            notes_content = notes_assembly.text
            complete_proof = await self.assistant.compile_complete_proof(
                notes_content,
                self.problem,
                extra_metadata={
                    "assembly_profile": notes_assembly.profile,
                    "document_char_counts": notes_assembly.section_char_counts,
                },
            )

            self._emit(
                ThinkingEvent(
                    "proof_compiled",
                    content="Complete proof compiled from all step proofs.",
                    metadata={
                        "complete_proof": complete_proof,
                        "notes_assembly_profile": notes_assembly.profile,
                        "notes_section_char_counts": notes_assembly.section_char_counts,
                    },
                )
            )

            max_repair_attempts = 2
            review_passed = False

            for repair_attempt in range(max_repair_attempts + 1):
                review_runtime = (
                    self.review_runtime.fork(
                        role=f"review-{self._roadmaps_attempted}-{repair_attempt}",
                        root_dir=self.review_runtime.root_dir / f"roadmap_{self._roadmaps_attempted}" / f"attempt_{repair_attempt}",
                        workspace=self.review_runtime.workspace,
                    )
                    if self.review_runtime is not None
                    else self.thinking.runtime.fork(
                        role=f"review-{self._roadmaps_attempted}-{repair_attempt}",
                        root_dir=self.thinking.runtime.root_dir.parent / "review" / f"roadmap_{self._roadmaps_attempted}" / f"attempt_{repair_attempt}",
                        workspace=self.thinking.runtime.workspace,
                    )
                )
                reviewer = ReviewAgent(review_runtime)
                cited_claims = [
                    prop.prop_id
                    for prop in self.memo.load().proved_propositions
                    if prop.prop_id in complete_proof
                ]
                review_context_assembly, review_proof_assembly = self._assemble_review_package(
                    complete_proof=complete_proof,
                    roadmap_summary=roadmap_summary,
                    cited_claims=cited_claims,
                )
                review_context = review_context_assembly.text
                review_proof = review_proof_assembly.text
                review = await reviewer.review_proof(
                    self.problem,
                    review_proof,
                    review_context,
                    extra_metadata={
                        "assembly_profile": ",".join(
                            part
                            for part in [
                                f"context:{review_context_assembly.profile}",
                                f"proof:{review_proof_assembly.profile}",
                            ]
                            if part
                        ),
                        "document_char_counts": {
                            **review_context_assembly.section_char_counts,
                            "review_proof": len(review_proof),
                        },
                    },
                )

                self._emit(
                    ThinkingEvent(
                        "review_result",
                        content=review.reasoning,
                        metadata={
                            "has_gaps": review.has_gaps,
                            "confidence": review.confidence,
                            "verdict": review.verdict,
                            "format_valid": review.format_valid,
                            "repair_attempt": repair_attempt,
                            "complete_proof": complete_proof if not review.has_gaps else None,
                            "review_assembly_profile": review_context_assembly.profile,
                            "review_section_char_counts": review_context_assembly.section_char_counts,
                            "review_proof_profile": review_proof_assembly.profile,
                        },
                    )
                )

                review_accepted = (
                    review.format_valid
                    and review.verdict == "PASS"
                    and not review.has_gaps
                    and review.confidence >= 0.55
                )
                if review_accepted:
                    self.memo.mark_review_outcome(
                        self._roadmaps_attempted,
                        roadmap_id=roadmap_id,
                        accepted=True,
                    )
                    review_passed = True
                    break

                # --- Gap Repair: fix specific gaps instead of full restart ---
                if (
                    repair_attempt < max_repair_attempts
                    and review.format_valid
                    and review.gaps
                    and review.confidence >= 0.3
                ):
                    # Proof is mostly correct -- try targeted repair
                    self._emit(
                        ThinkingEvent(
                            "gap_repair",
                            content=(
                                f"Attempting targeted gap repair (attempt {repair_attempt + 1}/{max_repair_attempts}). "
                                f"Confidence: {review.confidence:.2f}. "
                                f"Gaps: {', '.join(review.gaps[:3])}"
                            ),
                            metadata={
                                "gaps": review.gaps,
                                "confidence": review.confidence,
                            },
                        )
                    )

                    repair_proof_assembly, reviewer_reasoning = self._assemble_repair_package(
                        complete_proof=complete_proof,
                        gaps=review.gaps,
                        reviewer_reasoning=review.reasoning,
                    )
                    complete_proof = await self.thinking.repair_proof(
                        self.problem,
                        repair_proof_assembly.text,
                        review.gaps,
                        reviewer_reasoning,
                    )

                    self._emit(
                        ThinkingEvent(
                            "proof_compiled",
                            content=f"Proof repaired (attempt {repair_attempt + 1}). Re-reviewing.",
                            metadata={
                                "complete_proof": complete_proof,
                                "repair_proof_profile": repair_proof_assembly.profile,
                            },
                        )
                    )
                    continue
                else:
                    # Confidence too low or repair attempts exhausted
                    break

            if review_passed:
                # --- Blind Falsifier check ---
                falsifier_passed = True
                falsifier_feedback = "Falsifier rejected proof"
                falsifier_assembly = self._assemble_falsifier_input(complete_proof)
                falsifier_input = falsifier_assembly.text

                if self.falsifier is not None:
                    self._emit(
                        ThinkingEvent(
                            "falsifier_started",
                            content="Running blind falsifier (no proof context, Python sandbox).",
                        )
                    )

                    try:
                        falsify_result = await self.falsifier.falsify(
                            self.problem,
                            falsifier_input,
                            extra_metadata={
                                "assembly_profile": falsifier_assembly.profile,
                                "document_char_counts": falsifier_assembly.section_char_counts,
                            },
                        )

                        python_summary = ""
                        if falsify_result.python_checks:
                            n_passed = sum(1 for c in falsify_result.python_checks if c.passed)
                            n_total = len(falsify_result.python_checks)
                            python_summary = f" Python checks: {n_passed}/{n_total} passed."

                        self._emit(
                            ThinkingEvent(
                                "falsifier_result",
                                content=(
                                    f"Verdict: {falsify_result.verdict}. "
                                    f"Counterexample: {bool(falsify_result.has_counterexample)}. "
                                    f"Missing cases: {len(falsify_result.missing_cases)}.{python_summary}"
                                ),
                                metadata={
                                    "verdict": falsify_result.verdict,
                                    "has_counterexample": falsify_result.has_counterexample,
                                    "counterexample": falsify_result.counterexample,
                                    "missing_cases": falsify_result.missing_cases,
                                    "reasoning": falsify_result.reasoning,
                                    "suggestions": falsify_result.suggestions,
                                    "falsifier_assembly_profile": falsifier_assembly.profile,
                                },
                            )
                        )

                        if falsify_result.verdict != "PASS":
                            falsifier_passed = False
                            # Build failure reason from falsifier feedback
                            failure_parts = []
                            if falsify_result.has_counterexample:
                                failure_parts.append(
                                    f"Counterexample: {falsify_result.counterexample}"
                                )
                            if falsify_result.missing_cases:
                                failure_parts.append(
                                    f"Missing cases: {', '.join(falsify_result.missing_cases)}"
                                )
                            if falsify_result.suggestions:
                                failure_parts.append(
                                    f"Suggestions: {', '.join(falsify_result.suggestions)}"
                                )
                            falsifier_feedback = (
                                "; ".join(failure_parts)
                                or falsify_result.reasoning
                                or f"Falsifier verdict: {falsify_result.verdict}"
                            )

                            logger.warning(
                                "Falsifier rejected proof: %s",
                                falsifier_feedback[:200],
                            )

                    except Exception as exc:
                        logger.warning("Falsifier raised an exception: %s", exc)
                        falsifier_passed = False
                        falsifier_feedback = f"Falsifier error: {exc}"

                if falsifier_passed:
                    return Phase1Result(
                        success=True,
                        complete_proof=complete_proof,
                        memo_state=self.memo.load(),
                        events=self._events,
                        roadmaps_attempted=self._roadmaps_attempted,
                    )

                # Falsifier rejected -- archive roadmap with falsifier feedback
                achieved = [
                    p.prop_id for p in self.memo.load().proved_propositions
                ]
                self.memo.archive_roadmap(
                    f"Roadmap {self._roadmaps_attempted}",
                    chosen.get("approach", ""),
                    f"Falsifier rejected: {falsifier_feedback[:300]}",
                    achieved,
                    f"Falsifier FAIL: {falsifier_feedback}",
                    roadmap_id=roadmap_id,
                )
                self.memo.store_runner_ups([])
                self.memo.record_falsifier_failure(
                    self._roadmaps_attempted,
                    roadmap_id=roadmap_id,
                    feedback=falsifier_feedback,
                )

                # --- P4: Auto-enqueue SUFFICIENCY lemma after falsifier rejection ---
                from math_agent.documents.memo import AuxiliaryLemma
                self.memo.enqueue_lemma(AuxiliaryLemma(
                    lemma_type="sufficiency",
                    statement=f"Verify sufficiency: {falsifier_feedback[:200]}",
                    source=f"falsifier rejection (roadmap {self._roadmaps_attempted})",
                    unblocks=[],
                ))
                self._emit(
                    ThinkingEvent(
                        "lemma_enqueued",
                        content=f"Enqueued SUFFICIENCY lemma from falsifier feedback.",
                        metadata={"lemma_type": "sufficiency", "source": "falsifier"},
                    )
                )

                continue

            # Review found gaps even after repair attempts -- archive and try new roadmap.
            # Pass review_rejected=True so archive_roadmap flags every proposition
            # produced by this roadmap as suspect. Without this, review-rejected
            # lemmas (e.g. an unproven floor-inequality claim) would remain in the
            # trusted "Proved Propositions" section and the next roadmap's planner
            # would happily invoke them as premises.
            repair_note = ""
            if review.confidence >= 0.3:
                repair_note = f" (after {max_repair_attempts} repair attempt(s))"
            self.memo.mark_review_outcome(
                self._roadmaps_attempted,
                roadmap_id=roadmap_id,
                accepted=False,
                gaps=review.gaps,
            )
            achieved = [
                p.prop_id for p in self.memo.load().proved_propositions
            ]
            self.memo.archive_roadmap(
                f"Roadmap {self._roadmaps_attempted}",
                chosen.get("approach", ""),
                f"Review found gaps{repair_note}: {', '.join(review.gaps)}",
                achieved,
                f"Review confidence: {review.confidence:.2f}. Gaps: {', '.join(review.gaps)}",
                review_rejected=True,
                roadmap_id=roadmap_id,
            )
            self.memo.store_runner_ups([])

        # Exhausted all roadmap attempts
        return Phase1Result(
            success=False,
            memo_state=self.memo.load(),
            events=self._events,
            roadmaps_attempted=self._roadmaps_attempted,
        )

    # ------------------------------------------------------------------
    # P6: Handoff builder
    # ------------------------------------------------------------------

    def _build_handoff(
        self,
        steps: list[RoadmapStep],
        current_step: RoadmapStep,
        roadmap_summary: str,
    ) -> HandoffPacket:
        """Build a structured handoff packet at the moment of context reset.

        Captures the agent's working state so the next session can resume
        precisely instead of re-deriving everything from prose MEMO.
        """
        proved = [s for s in steps if s.status == "PROVED"]
        remaining = [s for s in steps if s.status in ("UNPROVED", "IN_PROGRESS")]
        failed = [s for s in steps if s.status == "FAILED"]
        reusable_prop_ids = [
            prop.prop_id
            for prop in self.memo.load().proved_propositions
            if not prop.suspect
        ]
        proof_keys = list(dict.fromkeys(
            key
            for s in proved
            for key in s.lemma_dependencies
            if key
        ))
        proof_note_ids = list(
            dict.fromkeys(
                prop.note_id
                for prop in self.memo.load().proved_propositions
                if not prop.suspect and prop.note_id
            )
        )
        proof_summaries = [
            entry.summary
            for entry in self.memo.load().proof_index
            if entry.prop_id in set(proof_keys)
        ]
        coverage = self._roadmap_coverage(steps)
        open_obligations = [
            key for key in coverage["missing_after_proved"] if isinstance(key, str)
        ]
        if current_step.status in ("UNPROVED", "IN_PROGRESS"):
            active_step_label = (
                f"Step {current_step.step_index}: {current_step.description}"
            )
        elif remaining:
            active_step_label = (
                f"Step {remaining[0].step_index}: {remaining[0].description}"
            )
        else:
            active_step_label = ""
        recent_diagnoses = [
            f"step {s.step_index}: {s.result[:160]}"
            for s in failed
            if s.result
        ]

        # Next action
        if current_step.status in ("UNPROVED", "IN_PROGRESS"):
            next_action = f"Continue proving step {current_step.step_index}: {current_step.description}"
        elif remaining:
            next_action = f"Prove step {remaining[0].step_index}: {remaining[0].description}"
        else:
            next_action = "All steps attempted; review the proof."

        # Open questions
        open_questions = []
        if remaining:
            open_questions.append(
                f"{len(remaining)} step(s) still unproved: "
                + ", ".join(f"step {s.step_index}" for s in remaining)
            )
        if failed:
            open_questions.append(
                f"{len(failed)} step(s) failed: "
                + ", ".join(f"step {s.step_index}" for s in failed)
                + ". Consider alternative approaches."
            )

        # Strategy
        current_strategy = roadmap_summary[:300]

        # Blockers
        blockers = []
        if failed:
            for s in failed:
                blockers.append(
                    f"Step {s.step_index} ({s.description[:60]}) failed"
                    + (f": {s.result[:100]}" if s.result else "")
                )
        if open_obligations:
            blockers.append(
                "Open obligations: " + ", ".join(open_obligations[:5])
            )

        # Confidence
        if not steps:
            confidence = 0.5
        else:
            confidence = len(proved) / len(steps)

        # Token count
        token_count = self.compressor._estimate_tokens(self.thinking.context)

        return HandoffPacket(
            next_action=next_action,
            open_questions=open_questions,
            current_strategy=current_strategy,
            blockers=blockers,
            confidence=confidence,
            context_tokens_before_reset=token_count,
            roadmap_number=self._roadmaps_attempted,
            roadmap_id=current_step.roadmap_id,
            current_step_index=current_step.step_index,
            current_step_id=current_step.step_id,
            proved_steps=[s.step_index for s in proved],
            remaining_steps=[s.step_index for s in remaining],
            failed_steps=[s.step_index for s in failed],
            reusable_prop_ids=reusable_prop_ids,
            proof_keys=proof_keys,
            proof_note_ids=proof_note_ids[:12],
            proof_summaries=proof_summaries[:8],
            recent_diagnoses=recent_diagnoses[:6],
            active_step_label=active_step_label,
            open_obligations=open_obligations,
        )
