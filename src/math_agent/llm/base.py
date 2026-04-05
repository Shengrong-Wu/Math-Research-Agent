from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)  # input_tokens, output_tokens


class BaseLLMClient(ABC):
    """Base interface for all LLM providers."""

    def __init__(self, model: str, temperature: float = 0.7, api_key: str = ""):
        self.model = model
        self.temperature = temperature
        self.api_key = api_key

    @abstractmethod
    async def generate(self, messages: list[LLMMessage], system: str = "") -> LLMResponse:
        """Send messages and get a response."""
        ...

    @abstractmethod
    async def generate_stream(self, messages: list[LLMMessage], system: str = ""):
        """Stream response chunks. Yields str chunks."""
        ...

    def default_model(self) -> str:
        """Return provider's default model name."""
        return self.model
