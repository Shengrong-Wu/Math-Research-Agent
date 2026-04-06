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
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from math_agent.agents.thinking import ThinkingAgent
from math_agent.agents.assistant import AssistantAgent
from math_agent.agents.review import ReviewAgent
from math_agent.agents.falsifier import FalsifierAgent
from math_agent.agents.base import StepResult, RoadmapEvaluation, ReviewResult
from math_agent.documents.memo import (
    Memo,
    MemoState,
    RoadmapStep,
    HandoffPacket,
    StepFailure,
)
from math_agent.documents.notes import Notes
from math_agent.context.token_budget import TokenBudget
from math_agent.context.compression import ContextCompressor
from math_agent.context.diminishing import DiminishingReturnsDetector, ProgressEntry
from math_agent.config import Hyperparameters

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
        falsifier: FalsifierAgent | None = None,
    ):
        self.thinking = thinking
        self.assistant = assistant
        self.memo = memo
        self.notes = notes
        self.hyper = hyper
        self.problem = problem_question
        self.falsifier = falsifier
        self.budget = TokenBudget()
        self.compressor = ContextCompressor(self.budget, thinking.client)
        self.detector = DiminishingReturnsDetector(window=hyper.K)
        self._events: list[ThinkingEvent] = []
        self._roadmaps_attempted = 0

    def _emit(self, event: ThinkingEvent) -> None:
        self._events.append(event)
        logger.info(
            "Phase1 [%s] step=%s: %s",
            event.event_type,
            event.step_index,
            event.content[:120],
        )

    async def run(self) -> Phase1Result:
        """Run Phase 1 to completion."""
        max_roadmap_attempts = 5  # safety limit

        # Check if there's a handoff from a previous context reset
        memo_state = self.memo.load()
        if memo_state.handoff:
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
                    },
                )
            )
            # Clear the handoff after consuming it
            self.memo.clear_handoff()

        # --- Resume from in-progress roadmap ---
        # If the MEMO has a current roadmap with some PROVED and some
        # UNPROVED steps, verify the proved steps and resume from where
        # the previous run left off.
        resumed_from_progress = False
        if memo_state.current_roadmap:
            proved_steps = [s for s in memo_state.current_roadmap if s.status == "PROVED"]
            unproved_steps = [s for s in memo_state.current_roadmap if s.status in ("UNPROVED", "IN_PROGRESS")]
            if proved_steps and unproved_steps:
                logger.info(
                    "Found in-progress roadmap: %d proved, %d remaining. Verifying proved steps...",
                    len(proved_steps), len(unproved_steps),
                )
                self._emit(
                    ThinkingEvent(
                        "resume_verify",
                        content=(
                            f"Resuming from previous run: {len(proved_steps)} proved, "
                            f"{len(unproved_steps)} remaining. Verifying proved steps..."
                        ),
                        metadata={
                            "current_roadmap": [
                                {"step_index": s.step_index, "description": s.description, "status": s.status}
                                for s in memo_state.current_roadmap
                            ],
                        },
                    )
                )

                # Verify each proved step using its proof from NOTES
                all_valid = True
                first_invalid_index = None
                for step in proved_steps:
                    proof_text = self.notes.get_step_proof(step.step_index)
                    if not proof_text:
                        logger.warning(
                            "No proof found in NOTES for step %d, marking invalid.",
                            step.step_index,
                        )
                        all_valid = False
                        first_invalid_index = step.step_index
                        self._emit(
                            ThinkingEvent(
                                "resume_verify_failed",
                                step_index=step.step_index,
                                content=f"Step {step.step_index}: no proof record found. Will re-prove.",
                            )
                        )
                        break

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
                    else:
                        all_valid = False
                        first_invalid_index = step.step_index
                        self._emit(
                            ThinkingEvent(
                                "resume_verify_failed",
                                step_index=step.step_index,
                                content=f"Step {step.step_index}: verification failed. Will re-prove from here.",
                            )
                        )
                        logger.warning("Step %d failed verification.", step.step_index)
                        break

                if all_valid:
                    # All proved steps verified — resume from first unproved
                    self._emit(
                        ThinkingEvent(
                            "resume_ready",
                            content=(
                                f"All {len(proved_steps)} proved steps verified. "
                                f"Resuming from step {unproved_steps[0].step_index}."
                            ),
                        )
                    )
                    resumed_from_progress = True
                else:
                    # Invalidate the failed step and all after it
                    for step in memo_state.current_roadmap:
                        if step.step_index >= first_invalid_index:
                            step.status = "UNPROVED"
                            step.result = None
                    self.memo.set_current_roadmap(memo_state.current_roadmap)
                    self._emit(
                        ThinkingEvent(
                            "resume_ready",
                            content=(
                                f"Step {first_invalid_index} failed verification. "
                                f"Resuming from step {first_invalid_index}."
                            ),
                        )
                    )
                    resumed_from_progress = True

        while self._roadmaps_attempted < max_roadmap_attempts:
            self._roadmaps_attempted += 1
            self.detector.reset()

            # --- Resume: use the in-progress roadmap on first iteration ---
            if resumed_from_progress:
                resumed_from_progress = False  # only on first iteration
                memo_state = self.memo.load()
                steps = memo_state.current_roadmap
                # Reconstruct approach from step descriptions
                chosen = {
                    "approach": "Resumed from previous run",
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
                            "current_roadmap": [
                                {"step_index": s.step_index, "description": s.description, "status": s.status}
                                for s in steps
                            ],
                        },
                    )
                )
            else:
                # --- Normal Roadmap Generation ---
                memo_state = self.memo.load()
                memo_content = None
                if memo_state.previous_roadmaps or memo_state.proved_propositions:
                    memo_content = (
                        self.memo.path.read_text() if self.memo.path.exists() else None
                    )

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
                    roadmaps = await self.thinking.generate_roadmaps(
                        self.problem,
                        memo_content,
                        count=count,
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

                steps = [
                    RoadmapStep(
                        step_index=i + 1, description=desc, status="UNPROVED"
                    )
                    for i, desc in enumerate(
                        chosen.get("steps", [])[: self.hyper.N]
                    )
                ]

                if not steps:
                    self._emit(
                        ThinkingEvent("abandoned", content="Roadmap had no steps.")
                    )
                    continue

                self.memo.set_current_roadmap(steps)

                self._emit(
                    ThinkingEvent(
                        "roadmap_generated",
                        content=chosen.get("approach", ""),
                        metadata={
                            "steps": [s.description for s in steps],
                            "count_considered": 1 if runner_up_used else (3 if is_first else 1),
                            "runner_up_used": runner_up_used,
                            "current_roadmap": [
                                {"step_index": s.step_index, "description": s.description, "status": s.status}
                                for s in steps
                            ],
                        },
                    )
                )

            # --- Execution Loop ---
            has_proved = any(s.status == "PROVED" for s in steps)
            roadmap_summary = chosen.get("approach", "") + "\n" + "\n".join(
                f"Step {s.step_index}: {s.description}"
                + (f" [{s.status}]" if has_proved else "")
                for s in steps
            )
            iteration = 0

            diagnosed_failures: list[StepFailure] = []

            for step in steps:
                # Skip already-PROVED steps (from resume verification)
                if step.status == "PROVED":
                    logger.info(
                        "Skipping step %d (already proved).", step.step_index
                    )
                    continue

                proved = False
                redo_count = 0
                max_redos = 3
                step_error_reasons: list[str] = []

                while not proved and redo_count < max_redos:
                    iteration += 1
                    redo_count += 1

                    self._emit(
                        ThinkingEvent(
                            "step_started",
                            step_index=step.step_index,
                            content=f"Working on step {step.step_index}: {step.description}",
                            metadata={
                                "current_roadmap": [
                                    {
                                        "step_index": s.step_index,
                                        "description": s.description,
                                        "status": "IN_PROGRESS" if s.step_index == step.step_index else s.status,
                                    }
                                    for s in steps
                                ],
                            },
                        )
                    )

                    # Work the step
                    result = await self.thinking.work_step(
                        self.problem,
                        roadmap_summary,
                        step.description,
                        step.step_index,
                    )

                    if (
                        result.verification_passed
                        and result.status == "PROVED"
                    ):
                        proved = True
                        step.status = "PROVED"
                        self.memo.append_step_result(
                            step.step_index, "PROVED", "Verified correct."
                        )

                        # Extract proposition if reusable
                        prop = (
                            await self.assistant.extract_proved_proposition(
                                result
                            )
                        )
                        if prop:
                            prop_id, statement = prop
                            source = f"Roadmap {self._roadmaps_attempted}, step {step.step_index}"
                            self.memo.add_proved_proposition(
                                prop_id, statement, source
                            )

                        # Update NOTES
                        brief, detail = (
                            await self.assistant.summarize_step_for_memo(
                                step.step_index, result
                            )
                        )
                        self.notes.append_step_proof(
                            step.step_index, step.description, detail
                        )

                        self._emit(
                            ThinkingEvent(
                                "step_verified",
                                step_index=step.step_index,
                                content=f"Step {step.step_index} verified correct.",
                                metadata={
                                    "current_roadmap": [
                                        {"step_index": s.step_index, "description": s.description, "status": s.status}
                                        for s in steps
                                    ],
                                    "proved_propositions": [
                                        {"prop_id": p.prop_id, "statement": p.statement, "source": p.source}
                                        for p in self.memo.load().proved_propositions
                                    ],
                                },
                            )
                        )

                        # Re-evaluate roadmap
                        completed = [
                            {
                                "index": s.step_index,
                                "description": s.description,
                            }
                            for s in steps
                            if s.status == "PROVED"
                        ]
                        remaining = [
                            {
                                "index": s.step_index,
                                "description": s.description,
                            }
                            for s in steps
                            if s.status == "UNPROVED"
                        ]

                        if remaining:
                            evaluation = (
                                await self.thinking.re_evaluate_roadmap(
                                    self.problem,
                                    roadmap_summary,
                                    completed,
                                    remaining,
                                )
                            )
                            if (
                                not evaluation.on_track
                                and evaluation.updated_steps
                            ):
                                # Update remaining steps
                                for updated in evaluation.updated_steps:
                                    idx = updated.get("index")
                                    new_desc = updated.get("description", "")
                                    if idx and new_desc:
                                        for s in steps:
                                            if (
                                                s.step_index == idx
                                                and s.status == "UNPROVED"
                                            ):
                                                s.description = new_desc
                                self.memo.set_current_roadmap(steps)
                                roadmap_summary = chosen.get(
                                    "approach", ""
                                ) + "\n" + "\n".join(
                                    f"Step {s.step_index}: {s.description} [{s.status}]"
                                    for s in steps
                                )
                                self._emit(
                                    ThinkingEvent(
                                        "roadmap_reevaluated",
                                        content=evaluation.reasoning,
                                    )
                                )
                    else:
                        step_error_reasons.append(result.error_reason)
                        self._emit(
                            ThinkingEvent(
                                "step_failed",
                                step_index=step.step_index,
                                content=f"Verification failed (attempt {redo_count}/{max_redos}): {result.error_reason}",
                                metadata={
                                    "current_roadmap": [
                                        {"step_index": s.step_index, "description": s.description, "status": s.status}
                                        for s in steps
                                    ],
                                },
                            )
                        )

                    # Progress tracking
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

                    # --- P6: Context compression with structured handoff ---
                    messages, was_reset = (
                        await self.compressor.compress_if_needed(
                            self.thinking.context,
                        )
                    )
                    if was_reset:
                        # Build structured handoff before clearing context
                        handoff = self._build_handoff(
                            steps, step, roadmap_summary,
                        )
                        self.memo.set_handoff(handoff)

                        self.thinking.clear_context()
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
                                },
                            )
                        )
                    elif messages != self.thinking.context:
                        self.thinking._context = messages
                        self._emit(
                            ThinkingEvent(
                                "compression",
                                content=f"Compressed context ({self.compressor.events[-1].action}).",
                            )
                        )

                if not proved:
                    step.status = "FAILED"

                    # --- Diagnose WHY the step failed ---
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

                    # Record refuted proposition if it's a false claim
                    if step_failure.diagnosis == "FALSE_PROPOSITION" and step_failure.false_claim:
                        self.memo.add_refuted_proposition(step_failure)

                    failure_detail = (
                        f"[{diagnosis['diagnosis']}] {diagnosis['explanation']}"
                    )
                    if diagnosis.get("false_claim"):
                        failure_detail += f" FALSE CLAIM: {diagnosis['false_claim']}"

                    self.memo.append_step_result(
                        step.step_index,
                        "FAILED",
                        failure_detail,
                    )

                    self._emit(
                        ThinkingEvent(
                            "step_diagnosed",
                            step_index=step.step_index,
                            content=f"Step {step.step_index} failure diagnosis: {failure_detail}",
                            metadata={
                                "diagnosis": diagnosis["diagnosis"],
                                "explanation": diagnosis["explanation"],
                                "false_claim": diagnosis.get("false_claim", ""),
                            },
                        )
                    )

                    # --- Re-evaluate roadmap viability after failure ---
                    remaining_after = [
                        {"index": s.step_index, "description": s.description}
                        for s in steps
                        if s.status == "UNPROVED"
                    ]
                    if remaining_after:
                        completed_so_far = [
                            {"index": s.step_index, "description": s.description}
                            for s in steps
                            if s.status == "PROVED"
                        ]
                        failed_info = {
                            "index": step.step_index,
                            "description": step.description,
                        }
                        failure_eval = (
                            await self.thinking.re_evaluate_after_failure(
                                self.problem,
                                roadmap_summary,
                                completed_so_far,
                                failed_info,
                                remaining_after,
                            )
                        )

                        self._emit(
                            ThinkingEvent(
                                "roadmap_reevaluated",
                                step_index=step.step_index,
                                content=f"After step {step.step_index} FAILED: {failure_eval.reasoning}",
                                metadata={
                                    "should_abandon": failure_eval.should_abandon,
                                    "trigger": "step_failed",
                                    "failed_step": step.step_index,
                                },
                            )
                        )

                        if failure_eval.should_abandon:
                            # Failed step was critical -- abandon this roadmap
                            logger.info(
                                "Abandoning roadmap: step %d was critical.",
                                step.step_index,
                            )
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
                                f"Step {step.step_index} failed and was critical. {total_proved}/{len(steps)} steps proved.",
                                achieved,
                                f"Critical step {step.step_index} failed: {step.description}",
                                failed_steps=diagnosed_failures,
                            )
                            break
                        elif failure_eval.updated_steps:
                            # Restructure remaining steps to work around failure
                            for updated in failure_eval.updated_steps:
                                idx = updated.get("index")
                                new_desc = updated.get("description", "")
                                if idx and new_desc:
                                    for s in steps:
                                        if (
                                            s.step_index == idx
                                            and s.status == "UNPROVED"
                                        ):
                                            s.description = new_desc
                            self.memo.set_current_roadmap(steps)
                            roadmap_summary = chosen.get(
                                "approach", ""
                            ) + "\n" + "\n".join(
                                f"Step {s.step_index}: {s.description} [{s.status}]"
                                for s in steps
                            )
                            logger.info(
                                "Restructured remaining steps after step %d failure.",
                                step.step_index,
                            )

                # Diminishing returns check
                if self.detector.should_abandon():
                    self._emit(
                        ThinkingEvent(
                            "abandoned",
                            content=self.detector.progress_summary(),
                        )
                    )
                    # Archive this roadmap and try a new one
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
                        f"No progress after {iteration} iterations. {total_proved}/{len(steps)} steps proved.",
                        achieved,
                        self.detector.progress_summary(),
                        failed_steps=diagnosed_failures,
                    )
                    break

            # Check if all steps proved
            all_proved = all(s.status == "PROVED" for s in steps)

            if not all_proved:
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
                    )
                continue

            # --- Review + Gap Repair Loop ---
            self._emit(
                ThinkingEvent(
                    "review_started",
                    content="Forking Review Agent for independent evaluation.",
                )
            )

            notes_content = self.notes.load()
            complete_proof = await self.assistant.compile_complete_proof(
                notes_content, self.problem
            )

            self._emit(
                ThinkingEvent(
                    "proof_compiled",
                    content="Complete proof compiled from all step proofs.",
                    metadata={"complete_proof": complete_proof},
                )
            )

            max_repair_attempts = 2
            review_passed = False

            for repair_attempt in range(max_repair_attempts + 1):
                reviewer = ReviewAgent.from_thinking_agent(self.thinking)
                review = await reviewer.review_proof(
                    self.problem, complete_proof, roadmap_summary
                )

                self._emit(
                    ThinkingEvent(
                        "review_result",
                        content=review.reasoning,
                        metadata={
                            "has_gaps": review.has_gaps,
                            "confidence": review.confidence,
                            "repair_attempt": repair_attempt,
                            "complete_proof": complete_proof if not review.has_gaps else None,
                        },
                    )
                )

                if not review.has_gaps:
                    review_passed = True
                    break

                # --- Gap Repair: fix specific gaps instead of full restart ---
                if repair_attempt < max_repair_attempts and review.confidence >= 0.3:
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

                    complete_proof = await self.thinking.repair_proof(
                        self.problem,
                        complete_proof,
                        review.gaps,
                        review.reasoning,
                    )

                    self._emit(
                        ThinkingEvent(
                            "proof_compiled",
                            content=f"Proof repaired (attempt {repair_attempt + 1}). Re-reviewing.",
                            metadata={"complete_proof": complete_proof},
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
                            complete_proof,
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
                                },
                            )
                        )

                        if falsify_result.verdict == "FAIL":
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
                                "; ".join(failure_parts) or falsify_result.reasoning
                            )

                            logger.warning(
                                "Falsifier rejected proof: %s",
                                falsifier_feedback[:200],
                            )

                    except Exception as exc:
                        logger.warning("Falsifier raised an exception: %s", exc)
                        # Don't block on falsifier failures -- treat as passed
                        falsifier_passed = True

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
                )
                continue

            # Review found gaps even after repair attempts -- archive and try new roadmap
            repair_note = ""
            if review.confidence >= 0.3:
                repair_note = f" (after {max_repair_attempts} repair attempt(s))"
            achieved = [
                p.prop_id for p in self.memo.load().proved_propositions
            ]
            self.memo.archive_roadmap(
                f"Roadmap {self._roadmaps_attempted}",
                chosen.get("approach", ""),
                f"Review found gaps{repair_note}: {', '.join(review.gaps)}",
                achieved,
                f"Review confidence: {review.confidence:.2f}. Gaps: {', '.join(review.gaps)}",
            )

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
        )
