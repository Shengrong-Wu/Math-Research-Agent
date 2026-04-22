from pathlib import Path

from math_agent.documents.memo import KGEdge, KGNode, KnowledgeGraph, MacroStep, Memo, RoadmapStep, StepFailure
from math_agent.documents.notes import Notes


def test_memo_round_trips_knowledge_graph(tmp_path: Path):
    memo = Memo(tmp_path / "MEMO.md")
    state = memo.load()
    state.knowledge_graph = KnowledgeGraph(
        nodes=[
            KGNode(
                node_id="strategy_1",
                node_type="strategy",
                statement="Try induction",
                status="proposed",
                source_attempt=1,
                source_step=None,
                evidence_summary="Generated from roadmap 1",
                reusable=True,
            ),
            KGNode(
                node_id="claim_P1",
                node_type="claim",
                statement="Lemma P1",
                status="argued",
                source_attempt=1,
                source_step=2,
                evidence_summary="proved at step 2",
                reusable=True,
            ),
        ],
        edges=[KGEdge(source="claim_P1", target="strategy_1", edge_type="depends_on")],
    )
    memo.save(state)

    reloaded = memo.load()
    assert len(reloaded.knowledge_graph.nodes) == 2
    assert reloaded.knowledge_graph.nodes[0].node_id == "strategy_1"
    assert reloaded.knowledge_graph.edges[0].edge_type == "depends_on"


def test_notes_render_for_compile_compacts_old_roadmaps(tmp_path: Path):
    notes = Notes(tmp_path / "NOTES.md")
    notes.append_step_proof(
        1,
        "Old step",
        "First old line.\nSecond old line.\nThird old line that should be compacted.",
        key="old_claim",
        roadmap_index=1,
    )
    notes.append_step_proof(
        2,
        "Recent step",
        "Recent proof line A.\nRecent proof line B.",
        key="recent_claim",
        roadmap_index=4,
    )

    rendered = notes.render_for_compile(current_roadmap=4, keep_recent_roadmaps=2, max_chars=10_000)
    assert "[compacted older proof note]" in rendered
    assert "Recent proof line A." in rendered


def test_memo_reviewer_render_surfaces_refuted_claims(tmp_path: Path):
    memo = Memo(tmp_path / "MEMO.md")
    memo.record_generated_strategy(
        "Roadmap 1",
        "Try contradiction",
        [],
    )
    memo.add_proved_proposition("P1", "A useful lemma", "Roadmap 1, step 1")
    memo.mark_review_outcome(1, accepted=False, gaps=["Lemma P1 not justified"])

    rendered = memo.render_for_reviewer(cited_claims=["P1"], max_chars=5_000)
    assert rendered is not None
    assert "Claim Trust Summary" in rendered
    assert "A useful lemma" in rendered


def test_failure_ledger_surfaces_repeated_motifs(tmp_path: Path):
    memo = Memo(tmp_path / "MEMO.md")
    memo.set_current_roadmap([])
    failure = StepFailure(
        step_index=3,
        description="Close induction base case",
        diagnosis="LOGICAL_GAP",
        explanation="Induction base case is false for n = 2.",
        false_claim="",
    )
    memo.archive_roadmap(
        "Roadmap 1",
        "Try induction",
        "Base case failed",
        [],
        "Base case false.",
        failed_steps=[failure],
    )
    memo.archive_roadmap(
        "Roadmap 2",
        "Try strong induction",
        "Base case failed again",
        [],
        "Base case false again.",
        failed_steps=[failure],
    )

    rendered = memo.render_failure_ledger(max_chars=5_000)
    assert rendered is not None
    assert "Failure Ledger" in rendered
    assert "x2" in rendered
    assert "LOGICAL_GAP" in rendered


def test_select_worker_proof_keys_returns_reusable_claim_ids(tmp_path: Path):
    memo = Memo(tmp_path / "MEMO.md")
    memo.add_proved_proposition("lemma_base", "Base case lemma", "Roadmap 1, step 1")
    memo.add_proved_proposition("lemma_step", "Induction step lemma", "Roadmap 1, step 2")

    keys = memo.select_worker_proof_keys("Use the base case lemma", max_items=2)

    assert "lemma_base" in keys


def test_set_current_roadmap_clears_stale_macro_roadmap(tmp_path: Path):
    memo = Memo(tmp_path / "MEMO.md")
    macro = [
        MacroStep(
            index=1,
            description="Macro",
            deliverable="Goal",
            sub_steps=[RoadmapStep(step_index=1, description="Old step", status="UNPROVED")],
        )
    ]
    memo.set_macro_roadmap(macro)
    memo.set_current_roadmap(
        [RoadmapStep(step_index=1, description="New flat step", status="UNPROVED")]
    )

    state = memo.load()
    assert state.macro_roadmap is None
    assert state.current_roadmap[0].description == "New flat step"


def test_memo_derives_obligations_frontier_and_proof_index(tmp_path: Path):
    memo = Memo(tmp_path / "MEMO.md")
    steps = [
        RoadmapStep(
            step_index=1,
            description="Derive the necessary conditions from the hypothesis.",
            status="PROVED",
            downstream_obligations=["necessary_direction"],
        ),
        RoadmapStep(
            step_index=2,
            description="Construct the object and prove the converse direction.",
            status="UNPROVED",
            downstream_obligations=[
                "existence_or_construction",
                "sufficiency_direction",
                "final_target_link",
            ],
        ),
    ]
    memo.set_current_roadmap(steps)
    memo.add_proved_proposition("lemma_base", "Base case lemma", "Roadmap 1, step 1")

    state = memo.load()
    obligation_map = {item.obligation_id: item for item in state.obligations}

    assert obligation_map["necessary_direction"].status == "covered"
    assert obligation_map["necessary_direction"].supporting_steps == [1]
    assert "lemma_base" in obligation_map["necessary_direction"].supporting_claim_ids
    assert obligation_map["sufficiency_direction"].status == "open"
    assert state.frontier is not None
    assert state.frontier.active_step_index == 2
    assert "sufficiency_direction" in state.frontier.open_obligations
    assert any(item.prop_id == "lemma_base" for item in state.proof_index)


def test_render_slim_surfaces_frontier_and_obligations(tmp_path: Path):
    memo = Memo(tmp_path / "MEMO.md")
    steps = [
        RoadmapStep(
            step_index=1,
            description="Prove the necessary direction.",
            status="PROVED",
            downstream_obligations=["necessary_direction"],
        ),
        RoadmapStep(
            step_index=2,
            description="Prove the converse direction.",
            status="UNPROVED",
            downstream_obligations=["sufficiency_direction", "final_target_link"],
        ),
    ]
    memo.set_current_roadmap(steps)

    rendered = memo.render_slim()

    assert rendered is not None
    assert "## Frontier" in rendered
    assert "## Theorem Obligations" in rendered
    assert "sufficiency_direction" in rendered


def test_archive_roadmap_clears_macro_roadmap(tmp_path: Path):
    memo = Memo(tmp_path / "MEMO.md")
    macro = [
        MacroStep(
            index=1,
            description="Macro",
            deliverable="Goal",
            sub_steps=[RoadmapStep(step_index=1, description="Old step", status="PROVED")],
        )
    ]
    memo.set_macro_roadmap(macro)
    memo.archive_roadmap(
        "Roadmap 1",
        "Macro approach",
        "Failed later",
        [],
        "Reset",
    )

    state = memo.load()
    assert state.current_roadmap == []
    assert state.macro_roadmap is None
