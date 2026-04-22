import asyncio

import pytest
from math_agent.context.compression import ContextCompressor
from math_agent.context.token_budget import TokenBudget
from math_agent.runtime import RuntimeMessage

class TestCompression:
    def test_compression_estimates_unseeded_budget_from_messages(self):
        budget = TokenBudget(max_tokens=10_000)
        compressor = ContextCompressor(budget)
        long_msg = RuntimeMessage("assistant", "x" * 25_000)
        messages = [RuntimeMessage("user", "Hi"), long_msg]
        result, reset = asyncio.run(compressor.compress_if_needed(messages))
        assert len(result[1].content) < 25_000
        assert not reset
        assert budget.pressure().used_tokens > 0

    def test_no_compression_low_pressure(self):
        budget = TokenBudget(max_tokens=200_000)
        budget.update(10_000)
        compressor = ContextCompressor(budget)
        messages = [RuntimeMessage("user", "Hello")]
        result, reset = asyncio.run(compressor.compress_if_needed(messages))
        assert result == messages
        assert not reset

    def test_layer1_truncates_long_messages(self):
        budget = TokenBudget(max_tokens=10_000)
        budget.update(7_000)  # 70% -> moderate
        compressor = ContextCompressor(budget)
        long_msg = RuntimeMessage("assistant", "x" * 25_000)
        messages = [RuntimeMessage("user", "Hi"), long_msg]
        result, reset = asyncio.run(compressor.compress_if_needed(messages))
        assert len(result[1].content) < 25_000
        assert not reset
