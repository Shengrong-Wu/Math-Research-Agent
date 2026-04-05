"""Base agent interface for all math proof agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from math_agent.llm.base import BaseLLMClient, LLMMessage, LLMResponse


@dataclass
class StepResult:
    """Result of working on a single proof step."""

    step_index: int
    status: str  # PROVED | FAILED | IN_PROGRESS | PARTIALLY_PROVED
    reasoning: str  # the thinking agent's reasoning
    proof_detail: str  # detailed proof if proved
    verification_passed: bool  # did the thinking agent verify this?
    error_reason: str = ""  # why it failed, if it did


@dataclass
class RoadmapEvaluation:
    """Result of re-evaluating the roadmap after a step."""

    on_track: bool
    updated_steps: list[dict] | None = None  # modified future steps if not on_track
    reasoning: str = ""


@dataclass
class ReviewResult:
    """Result of the review agent's independent evaluation."""

    has_gaps: bool
    gaps: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0-1
    reasoning: str = ""


class BaseAgent(ABC):
    """Base interface for all agents."""

    def __init__(self, client: BaseLLMClient):
        self.client = client
        self._context: list[LLMMessage] = []

    @property
    def context(self) -> list[LLMMessage]:
        """Return a shallow copy of the conversation context."""
        return list(self._context)

    def add_to_context(self, message: LLMMessage) -> None:
        """Append a message to the conversation context."""
        self._context.append(message)

    def clear_context(self) -> None:
        """Clear the conversation context."""
        self._context.clear()

    def fork(self) -> BaseAgent:
        """Create a copy of this agent with the same context but independent execution."""
        raise NotImplementedError
