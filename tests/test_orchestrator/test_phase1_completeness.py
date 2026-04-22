from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from math_agent.agents.base import CompletenessCheck
from math_agent.config import Hyperparameters
from math_agent.documents.memo import MacroStep, Memo, MemoState, RoadmapStep
from math_agent.documents.notes import Notes
from math_agent.orchestrator.phase1 import Phase1Runner


def _make_runner(tmp_path: Path) -> Phase1Runner:
    thinking = MagicMock()
    thinking.assess_completeness = AsyncMock()
    thinking.context = []
    thinking.runtime = MagicMock()
    thinking.runtime.invalidate_session = MagicMock()
    assistant = MagicMock()
    memo = Memo(tmp_path / "MEMO.md")
    notes = Notes(tmp_path / "NOTES.md")
    return Phase1Runner(
        thinking=thinking,
        assistant=assistant,
        memo=memo,
        notes=notes,
        hyper=Hyperparameters(),
        problem_question="Prove that A if and only if there exists an object X with property P.",
    )


def test_coverage_losses_detect_removed_sufficiency_step(tmp_path: Path):
    runner = _make_runner(tmp_path)
    steps = [
        RoadmapStep(
            step_index=1,
            description="Derive the necessary conditions from the hypothesis.",
            status="PROVED",
        ),
        RoadmapStep(
            step_index=2,
            description="For sufficiency, construct the object and verify it works.",
            status="UNPROVED",
        ),
    ]
    runner._annotate_step_obligations(steps)
    losses = runner._coverage_losses_from_update(
        steps,
        [{"index": 2, "description": "Derive an auxiliary inequality instead."}],
    )
    assert "sufficiency_direction" in losses


def test_pre_review_completeness_gate_appends_missing_steps(tmp_path: Path):
    runner = _make_runner(tmp_path)
    runner.thinking.assess_completeness.return_value = CompletenessCheck(
        is_complete=False,
        reasoning="Only the forward direction is proved.",
        missing_obligations=["sufficiency_direction", "existence_or_construction"],
        missing_steps=[
            "Construct the required object explicitly.",
            "Prove the converse direction using the construction.",
        ],
    )
    steps = [
        RoadmapStep(
            step_index=1,
            description="Prove the necessary direction of the equivalence.",
            status="PROVED",
        ),
        RoadmapStep(
            step_index=2,
            description="Record the derived constraints.",
            status="PROVED",
        ),
    ]
    runner._annotate_step_obligations(steps)
    runner.memo.set_current_roadmap(steps)

    complete, updated_summary = asyncio.run(
        runner._ensure_pre_review_completeness(
            approach="Necessary-conditions approach",
            steps=steps,
            macro_steps=None,
            roadmap_summary="Necessary-conditions approach",
        )
    )

    assert complete is False
    assert "Construct the required object explicitly." in updated_summary
    assert steps[-2].status == "UNPROVED"
    assert steps[-1].status == "UNPROVED"
    assert steps[-2].description == "Construct the required object explicitly."
    assert steps[-1].description == "Prove the converse direction using the construction."


def test_sanitize_resume_macro_state_discards_stale_macro(tmp_path: Path):
    runner = _make_runner(tmp_path)
    state = MemoState(
        current_roadmap=[
            RoadmapStep(step_index=1, description="Flat step", status="PROVED"),
        ],
        macro_roadmap=[
            MacroStep(
                index=1,
                description="Macro",
                deliverable="Goal",
                sub_steps=[
                    RoadmapStep(step_index=1, description="Different step", status="UNPROVED")
                ],
            )
        ],
    )
    runner.memo.save(state)

    sanitized = runner._sanitize_resume_macro_state(state)

    assert sanitized.macro_roadmap is None
    assert runner.memo.load().macro_roadmap is None


def test_review_package_compacts_large_proof(tmp_path: Path):
    runner = _make_runner(tmp_path)
    huge_proof = "A" * 80_000

    context_assembly, proof_assembly = runner._assemble_review_package(
        complete_proof=huge_proof,
        roadmap_summary="Roadmap summary",
        cited_claims=[],
    )

    assert context_assembly.chars <= 8_000
    assert proof_assembly.chars < len(huge_proof)
    assert proof_assembly.chars <= runner.prompt_budgets.review


def test_build_handoff_includes_active_step_label_and_open_obligations(tmp_path: Path):
    runner = _make_runner(tmp_path)
    steps = [
        RoadmapStep(
            step_index=1,
            description="Derive the necessary direction.",
            status="PROVED",
            downstream_obligations=["necessary_direction"],
            lemma_dependencies=["lemma_1"],
        ),
        RoadmapStep(
            step_index=2,
            description="Construct the object and prove the converse.",
            status="UNPROVED",
            downstream_obligations=[
                "existence_or_construction",
                "sufficiency_direction",
                "final_target_link",
            ],
        ),
    ]
    runner.memo.set_current_roadmap(steps)

    handoff = runner._build_handoff(
        steps,
        steps[1],
        "Two-step roadmap",
    )

    assert handoff.active_step_label == "Step 2: Construct the object and prove the converse."
    assert "sufficiency_direction" in handoff.open_obligations
