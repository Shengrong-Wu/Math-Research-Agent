import pytest
from math_agent.context.compression import ContextCompressor
from math_agent.context.token_budget import TokenBudget
from math_agent.llm.base import LLMMessage

class TestCompression:
    @pytest.mark.asyncio
    async def test_no_compression_low_pressure(self):
        budget = TokenBudget(max_tokens=200_000)
        budget.update(10_000)
        compressor = ContextCompressor(budget)
        messages = [LLMMessage("user", "Hello")]
        result, reset = await compressor.compress_if_needed(messages)
        assert result == messages
        assert not reset

    @pytest.mark.asyncio
    async def test_layer1_truncates_long_messages(self):
        budget = TokenBudget(max_tokens=10_000)
        budget.update(7_000)  # 70% -> moderate
        compressor = ContextCompressor(budget)
        long_msg = LLMMessage("assistant", "x" * 5000)
        messages = [LLMMessage("user", "Hi"), long_msg]
        result, reset = await compressor.compress_if_needed(messages)
        assert len(result[1].content) < 5000
        assert not reset
