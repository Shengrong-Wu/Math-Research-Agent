from __future__ import annotations
import pytest
from pathlib import Path
from math_agent.llm.base import BaseLLMClient, LLMMessage, LLMResponse

class MockLLMClient(BaseLLMClient):
    """Mock LLM client for testing."""

    def __init__(self, responses: list[str] | None = None):
        super().__init__(model="mock-model", temperature=0.0)
        self._responses = list(responses or ["Mock response."])
        self._call_count = 0
        self._calls: list[tuple[list[LLMMessage], str]] = []

    async def generate(self, messages: list[LLMMessage], system: str = "") -> LLMResponse:
        self._calls.append((messages, system))
        idx = min(self._call_count, len(self._responses) - 1)
        response = self._responses[idx]
        self._call_count += 1
        return LLMResponse(content=response, model="mock-model", usage={"input_tokens": 100, "output_tokens": 50})

    async def generate_stream(self, messages: list[LLMMessage], system: str = ""):
        response = await self.generate(messages, system)
        for word in response.content.split():
            yield word + " "

@pytest.fixture
def tmp_run_dir(tmp_path: Path) -> Path:
    d = tmp_path / "test_run"
    d.mkdir()
    return d

@pytest.fixture
def mock_client() -> MockLLMClient:
    return MockLLMClient()
