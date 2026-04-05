import pytest
import json
from math_agent.agents.thinking import ThinkingAgent
from tests.conftest import MockLLMClient

class TestThinkingAgent:
    @pytest.mark.asyncio
    async def test_generate_roadmaps_first_attempt(self):
        roadmap_json = json.dumps([{
            "approach": "Induction on n",
            "steps": ["Base case n=1", "Inductive hypothesis", "Inductive step"],
            "reasoning": "Standard induction approach"
        }])
        client = MockLLMClient(responses=[roadmap_json])
        agent = ThinkingAgent(client)
        roadmaps = await agent.generate_roadmaps("Prove sum of first n odds = n^2", None, count=3)
        assert len(roadmaps) >= 1
        assert "steps" in roadmaps[0]

    @pytest.mark.asyncio
    async def test_work_step_with_verification(self):
        client = MockLLMClient(responses=[
            "The base case is trivial: 1 = 1^2.",
            "VERIFIED: The proof is correct.",
        ])
        agent = ThinkingAgent(client)
        result = await agent.work_step(
            "Prove sum of first n odds = n^2",
            "Step 1: Base case",
            "Show P(1): 1 = 1^2",
            1,
        )
        assert result.step_index == 1
