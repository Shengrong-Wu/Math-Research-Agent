import asyncio

from conftest import MockRuntimeSession
from math_agent.agents.review import ReviewAgent
from math_agent.runtime import RuntimeMessage


def test_review_agent_runs_without_inherited_context():
    runtime = MockRuntimeSession(
        responses=["GAPS: NONE\nCONFIDENCE: 0.8\nREASONING: Looks consistent."],
        role="review",
    )
    agent = ReviewAgent(runtime)
    agent.add_to_context(RuntimeMessage(role="user", content="private thinking context"))

    result = asyncio.run(
        agent.review_proof(
            "Problem",
            "Complete proof",
            "Roadmap summary",
        )
    )

    assert result.has_gaps is False
    assert len(runtime.calls) == 1
    assert runtime.calls[0]["transcript"] == []
    assert runtime.calls[0]["metadata"]["callsite"] == "review.review_proof"
