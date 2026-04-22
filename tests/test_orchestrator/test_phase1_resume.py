"""Tests for Phase1Runner's resume-from-MEMO logic.

These exercise the `_try_resume_from_memo_state` helper directly (rather
than driving the full `run()` loop end-to-end) so the resume branches
can be validated without scaffolding a full proof-loop mock suite.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from math_agent.config import Hyperparameters
from math_agent.documents.memo import Memo, RoadmapStep
from math_agent.documents.notes import Notes
from math_agent.orchestrator.phase1 import Phase1Runner, ThinkingEvent


def _make_runner(
    tmp_path: Path,
    *,
    verify_responses: list[bool] | None = None,
) -> tuple[Phase1Runner, MagicMock]:
    """Build a minimal Phase1Runner with enough mocking for resume tests.

    The runner's thinking.verify_proved_step is mocked to return each
    response in *verify_responses* once (default: always True). The
    thinking.work_step mock raises AssertionError if ever called — the
    core invariant of these tests is that an all-PROVED resume must not
    re-prove any step.
    """
    thinking = MagicMock()
    thinking.verify_proved_step = AsyncMock(
        side_effect=verify_responses if verify_responses is not None else None,
        return_value=True if verify_responses is None else None,
    )
    thinking.work_step = AsyncMock(
        side_effect=AssertionError(
            "work_step must not be called during resume verification"
        )
    )
    # _inject_structured_premises touches thinking.context — give it a no-op.
    thinking.context = []
    thinking.runtime = MagicMock()
    thinking.runtime.invalidate_session = MagicMock()

    assistant = MagicMock()
    memo = Memo(tmp_path / "MEMO.md")
    notes = Notes(tmp_path / "NOTES.md")

    runner = Phase1Runner(
        thinking=thinking,
        assistant=assistant,
        memo=memo,
        notes=notes,
        hyper=Hyperparameters(),
        problem_question="Test problem",
    )
    return runner, thinking


def _make_proved_steps(count: int) -> list[RoadmapStep]:
    return [
        RoadmapStep(
            step_index=i,
            description=f"Step {i}: prove lemma {i}",
            status="PROVED",
            proof_text=f"Proof of step {i}: trivially true.",
        )
        for i in range(1, count + 1)
    ]


class TestPhase1ResumeAllProved:
    """Regression tests for the all-PROVED resume branch.

    Backstory: run 20260409_201742 had all 8 roadmap steps marked PROVED
    in MEMO.json, but the review agent's compiled-proof prompt tripped
    POSIX ARG_MAX at `roadmap_3/attempt_0` before the verdict could land.
    The follow-up resume run 20260409_214410 re-generated the roadmap
    from scratch and started from step 1 all over again — throwing away
    all the work plus re-invoking review-rejected lemmas.

    The fix (Phase1Runner._try_resume_from_memo_state all-PROVED branch)
    detects the all-PROVED MEMO, verifies each recorded proof, and
    returns True so run() drives the existing roadmap straight into the
    review-and-repair loop without re-proving any step.
    """

    def test_all_proved_returns_true_when_verification_passes(
        self, tmp_path: Path
    ):
        runner, thinking = _make_runner(tmp_path)
        memo_state = SimpleNamespace(
            current_roadmap=_make_proved_steps(3),
            macro_roadmap=None,
        )
        resumed = asyncio.run(runner._try_resume_from_memo_state(memo_state))

        assert resumed is True
        # Every step had its proof verified — never re-proved.
        assert thinking.verify_proved_step.await_count == 3
        thinking.work_step.assert_not_awaited()

        event_types = [e.event_type for e in runner._events]
        assert "resume_verify" in event_types
        assert "resume_ready" in event_types
        resume_verify = next(e for e in runner._events if e.event_type == "resume_verify")
        assert resume_verify.metadata["resume_mode"] == "all_proved"
        resume_ready = next(e for e in runner._events if e.event_type == "resume_ready")
        assert "review-and-repair loop" in resume_ready.content

    def test_all_proved_demotes_failed_step_and_downstream(
        self, tmp_path: Path
    ):
        """If step 2 of a 3-step all-PROVED roadmap fails verification,
        steps 2 and 3 must be demoted to UNPROVED so the main loop
        re-proves them, while step 1 stays PROVED."""
        runner, thinking = _make_runner(
            tmp_path,
            verify_responses=[True, False],  # step 1 OK, step 2 fails
        )
        steps = _make_proved_steps(3)
        memo_state = SimpleNamespace(
            current_roadmap=steps,
            macro_roadmap=None,
        )
        resumed = asyncio.run(runner._try_resume_from_memo_state(memo_state))

        assert resumed is True
        assert steps[0].status == "PROVED"
        assert steps[1].status == "UNPROVED"
        assert steps[2].status == "UNPROVED"
        # Verification stops at the first failure — step 3 was never checked.
        assert thinking.verify_proved_step.await_count == 2
        thinking.work_step.assert_not_awaited()

        # Persisted to disk so the main loop sees the demotion.
        reloaded = runner.memo.load()
        assert reloaded.current_roadmap[0].status == "PROVED"
        assert reloaded.current_roadmap[1].status == "UNPROVED"
        assert reloaded.current_roadmap[2].status == "UNPROVED"

    def test_all_proved_demotes_when_proof_text_is_missing(
        self, tmp_path: Path
    ):
        """Defensive: a PROVED step with no proof_text (and no NOTES
        entry either) cannot be trusted. It must be demoted rather than
        silently skipped during verify."""
        runner, thinking = _make_runner(tmp_path)
        steps = _make_proved_steps(2)
        steps[1].proof_text = ""  # missing proof
        memo_state = SimpleNamespace(
            current_roadmap=steps,
            macro_roadmap=None,
        )
        resumed = asyncio.run(runner._try_resume_from_memo_state(memo_state))

        assert resumed is True
        assert steps[0].status == "PROVED"
        assert steps[1].status == "UNPROVED"
        # verify_proved_step only called for step 1 — the missing proof
        # trips the guard before the LLM is invoked.
        assert thinking.verify_proved_step.await_count == 1

    def test_partial_roadmap_still_resumes(self, tmp_path: Path):
        """The original (pre-fix) partial-resume branch must still work."""
        runner, thinking = _make_runner(tmp_path)
        steps = _make_proved_steps(3)
        steps[1].status = "UNPROVED"
        steps[1].proof_text = ""
        steps[2].status = "UNPROVED"
        steps[2].proof_text = ""
        memo_state = SimpleNamespace(
            current_roadmap=steps,
            macro_roadmap=None,
        )
        resumed = asyncio.run(runner._try_resume_from_memo_state(memo_state))

        assert resumed is True
        assert thinking.verify_proved_step.await_count == 1  # just step 1
        thinking.work_step.assert_not_awaited()
        resume_verify = next(e for e in runner._events if e.event_type == "resume_verify")
        assert resume_verify.metadata["resume_mode"] == "partial"

    def test_empty_roadmap_returns_false(self, tmp_path: Path):
        """No current_roadmap → no resume → normal generate path."""
        runner, thinking = _make_runner(tmp_path)
        memo_state = SimpleNamespace(
            current_roadmap=[],
            macro_roadmap=None,
        )
        resumed = asyncio.run(runner._try_resume_from_memo_state(memo_state))

        assert resumed is False
        thinking.verify_proved_step.assert_not_awaited()
        thinking.work_step.assert_not_awaited()

    def test_all_unproved_returns_false(self, tmp_path: Path):
        """All-UNPROVED roadmap means no prior work to verify — generate."""
        runner, thinking = _make_runner(tmp_path)
        steps = [
            RoadmapStep(step_index=i, description=f"Step {i}", status="UNPROVED")
            for i in (1, 2, 3)
        ]
        memo_state = SimpleNamespace(
            current_roadmap=steps,
            macro_roadmap=None,
        )
        resumed = asyncio.run(runner._try_resume_from_memo_state(memo_state))

        assert resumed is False
        thinking.verify_proved_step.assert_not_awaited()
