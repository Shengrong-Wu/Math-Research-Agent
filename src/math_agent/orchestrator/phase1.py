"""Phase 1 loop: mathematical proof (roadmap -> execute -> review).

This is the core loop that implements the architecture from AGENT.md:
1. Roadmap Generation (3 on first attempt, 1 on subsequent)
2. Execution Loop (step-by-step proving with verification)
3. Review (forked Review Agent)
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
from math_agent.agents.base import StepResult, RoadmapEvaluation, ReviewResult
from math_agent.documents.memo import Memo, MemoState, RoadmapStep
from math_agent.documents.notes import Notes
from math_agent.context.token_budget import TokenBudget
from math_agent.context.compression import ContextCompressor
from math_agent.context.diminishing import DiminishingReturnsDetector, ProgressEntry
from math_agent.config import Hyperparameters

logger = logging.getLogger(__name__)


@dataclass
class ThinkingEvent:
    """Event emitted during Phase 1 for the Thinking Process panel."""

    event_type: str  # roadmap_generated | step_started | step_verified | step_failed | roadmap_reevaluated | review_started | review_result | compression | abandoned
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
    progressive compression, and diminishing-returns detection.
    """

    def __init__(
        self,
        thinking: ThinkingAgent,
        assistant: AssistantAgent,
        memo: Memo,
        notes: Notes,
        hyper: Hyperparameters,
        problem_question: str,
    ):
        self.thinking = thinking
        self.assistant = assistant
        self.memo = memo
        self.notes = notes
        self.hyper = hyper
        self.problem = problem_question
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

        while self._roadmaps_attempted < max_roadmap_attempts:
            self._roadmaps_attempted += 1
            self.detector.reset()

            # --- Roadmap Generation ---
            memo_state = self.memo.load()
            memo_content = None
            if memo_state.previous_roadmaps or memo_state.proved_propositions:
                memo_content = (
                    self.memo.path.read_text() if self.memo.path.exists() else None
                )

            is_first = self._roadmaps_attempted == 1 and memo_content is None
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
                        "count_considered": count,
                    },
                )
            )

            # --- Execution Loop ---
            roadmap_summary = chosen.get("approach", "") + "\n" + "\n".join(
                f"Step {s.step_index}: {s.description}" for s in steps
            )
            iteration = 0

            for step in steps:
                proved = False
                redo_count = 0
                max_redos = 3

                while not proved and redo_count < max_redos:
                    iteration += 1
                    redo_count += 1

                    self._emit(
                        ThinkingEvent(
                            "step_started",
                            step_index=step.step_index,
                            content=f"Working on step {step.step_index}: {step.description}",
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
                        self._emit(
                            ThinkingEvent(
                                "step_failed",
                                step_index=step.step_index,
                                content=f"Verification failed (attempt {redo_count}/{max_redos}): {result.error_reason}",
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

                    # Context compression check
                    messages, was_reset = (
                        await self.compressor.compress_if_needed(
                            self.thinking.context,
                        )
                    )
                    if was_reset:
                        self.thinking.clear_context()
                        self._emit(
                            ThinkingEvent(
                                "compression",
                                content="Full context renewal. Reading MEMO to resume.",
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
                    self.memo.append_step_result(
                        step.step_index,
                        "FAILED",
                        f"Failed after {max_redos} attempts.",
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
                    self.memo.archive_roadmap(
                        f"Roadmap {self._roadmaps_attempted}",
                        chosen.get("approach", ""),
                        f"{total_proved}/{len(steps)} steps proved. Remaining steps failed.",
                        achieved,
                        "Some steps could not be proved.",
                    )
                continue

            # --- Review ---
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
                    },
                )
            )

            if not review.has_gaps:
                return Phase1Result(
                    success=True,
                    complete_proof=complete_proof,
                    memo_state=self.memo.load(),
                    events=self._events,
                    roadmaps_attempted=self._roadmaps_attempted,
                )

            # Try to fix gaps
            # For now, if review finds gaps, archive and try new roadmap
            achieved = [
                p.prop_id for p in self.memo.load().proved_propositions
            ]
            self.memo.archive_roadmap(
                f"Roadmap {self._roadmaps_attempted}",
                chosen.get("approach", ""),
                f"Review found gaps: {', '.join(review.gaps)}",
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
