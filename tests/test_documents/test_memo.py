from __future__ import annotations
import pytest
from pathlib import Path
from math_agent.documents.memo import (
    Memo,
    MacroStep,
    RoadmapStep,
)

class TestMemo:
    def test_empty_load(self, tmp_path: Path):
        memo = Memo(tmp_path / "MEMO.md")
        state = memo.load()
        assert state.current_roadmap == []
        assert state.proved_propositions == []
        assert state.previous_roadmaps == []

    def test_set_roadmap_and_load(self, tmp_path: Path):
        memo = Memo(tmp_path / "MEMO.md")
        steps = [
            RoadmapStep(1, "Base case", "UNPROVED"),
            RoadmapStep(2, "Inductive step", "UNPROVED"),
        ]
        memo.set_current_roadmap(steps)
        state = memo.load()
        assert len(state.current_roadmap) == 2
        assert state.current_roadmap[0].description == "Base case"
        assert state.current_roadmap[0].status == "UNPROVED"

    def test_add_proved_proposition(self, tmp_path: Path):
        memo = Memo(tmp_path / "MEMO.md")
        memo.set_current_roadmap([RoadmapStep(1, "Step 1", "PROVED")])
        memo.add_proved_proposition("P1", "1 + 1 = 2", "Roadmap 1, step 1")
        state = memo.load()
        assert len(state.proved_propositions) == 1
        assert state.proved_propositions[0].prop_id == "P1"

    def test_archive_roadmap(self, tmp_path: Path):
        memo = Memo(tmp_path / "MEMO.md")
        memo.set_current_roadmap([RoadmapStep(1, "Step 1", "FAILED")])
        memo.archive_roadmap("Roadmap 1", "Induction approach", "Step 1 failed", ["P1"], "Don't use induction here")
        state = memo.load()
        assert len(state.previous_roadmaps) == 1
        assert state.previous_roadmaps[0].name == "Roadmap 1"

    def test_upsert_formal_artifact_and_archive_summary(self, tmp_path: Path):
        memo = Memo(tmp_path / "MEMO.md")
        steps = [RoadmapStep(1, "Prove lemma A", "FAILED")]
        memo.set_current_roadmap(steps)
        memo.upsert_formal_artifact(
            claim="Prove lemma A",
            proof_text="A detailed proof",
            claim_status="lean_sketch_checked",
            debt_label="none",
        )
        memo.archive_roadmap(
            "Roadmap 1",
            "Lemma-first approach",
            "Step failed",
            [],
            "Need a better lemma",
        )
        state = memo.load()
        assert state.previous_roadmaps[0].artifact_summaries
        assert "lean_sketch_checked" in state.previous_roadmaps[0].artifact_summaries[0]

    def test_macro_roadmap_and_runner_up_roundtrip(self, tmp_path: Path):
        memo = Memo(tmp_path / "MEMO.md")
        macro = MacroStep(
            index=1,
            description="Reduce to cases",
            deliverable="Case split",
            sub_steps=[
                RoadmapStep(1, "Handle case A", "UNPROVED"),
                RoadmapStep(2, "Handle case B", "UNPROVED"),
            ],
        )
        memo.set_macro_roadmap([macro])
        memo.store_runner_ups(
            [
                {
                    "approach": "Hierarchical fallback",
                    "steps": ["Handle case A", "Handle case B"],
                    "macro_steps": [
                        {
                            "description": "Reduce to cases",
                            "deliverable": "Case split",
                            "steps": ["Handle case A", "Handle case B"],
                        }
                    ],
                    "reasoning": "Keep the same structure",
                }
            ]
        )
        state = memo.load()
        assert state.macro_roadmap is not None
        assert state.macro_roadmap[0].deliverable == "Case split"
        assert state.runner_up_roadmaps[0].macro_steps[0]["deliverable"] == "Case split"
