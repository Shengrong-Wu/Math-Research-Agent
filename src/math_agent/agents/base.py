"""Base agent interface for all math proof agents."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from pathlib import Path

from math_agent.runtime import AgentRuntimeSession, RuntimeMessage, RuntimeResult


@dataclass
class StepResult:
    """Result of working on a single proof step."""

    step_index: int
    status: str
    reasoning: str
    proof_detail: str
    verification_passed: bool
    verification_outcome: str = "FAILED"
    verification_notes: str = ""
    derived_claim: str = ""
    false_claim: str = ""
    error_reason: str = ""


@dataclass
class RoadmapEvaluation:
    """Result of re-evaluating the roadmap after a step."""

    on_track: bool
    updated_steps: list[dict] | None = None
    reasoning: str = ""
    should_abandon: bool = False
    needs_extension: bool = False
    missing_obligations: list[str] = field(default_factory=list)


@dataclass
class CompletenessCheck:
    """Result of checking whether proved steps cover the whole theorem."""

    is_complete: bool
    reasoning: str = ""
    missing_obligations: list[str] = field(default_factory=list)
    missing_steps: list[str] = field(default_factory=list)


@dataclass
class ReviewResult:
    """Result of the review agent's independent evaluation."""

    has_gaps: bool
    gaps: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reasoning: str = ""
    verdict: str = "UNKNOWN"
    format_valid: bool = False


class BaseAgent(ABC):
    """Base interface for all agents."""

    def __init__(self, runtime: AgentRuntimeSession):
        self.runtime = runtime
        self._context: list[RuntimeMessage] = []

    @property
    def context(self) -> list[RuntimeMessage]:
        return list(self._context)

    def add_to_context(self, message: RuntimeMessage) -> None:
        self._context.append(message)

    def clear_context(self) -> None:
        self._context.clear()
        # The CLI side still holds the pre-clear conversation under our prior
        # session_id; resuming into it would silently re-introduce the wiped
        # history. Drop the id so the next invoke builds a fresh command.
        self.runtime.invalidate_session()

    async def _request_text(
        self,
        content: str,
        *,
        system_prompt: str,
        include_context: bool = True,
        context_window: int | None = None,
        record_history: bool = True,
        use_native_session: bool | None = None,
        cwd: Path | None = None,
        metadata: dict | None = None,
    ) -> RuntimeResult:
        if include_context:
            transcript = (
                list(self._context[-context_window:])
                if context_window is not None and context_window > 0
                else list(self._context)
            )
        else:
            transcript = []
        result = await self.runtime.invoke(
            system_prompt=system_prompt,
            transcript=transcript,
            prompt=content,
            use_native_session=use_native_session,
            cwd=cwd,
            metadata=metadata,
        )
        if record_history:
            self.add_to_context(RuntimeMessage(role="user", content=content))
            self.add_to_context(RuntimeMessage(role="assistant", content=result.content))
        return result

    async def _request_json(
        self,
        content: str,
        *,
        system_prompt: str,
        output_schema: dict,
        include_context: bool = True,
        context_window: int | None = None,
        record_history: bool = True,
        use_native_session: bool | None = None,
        cwd: Path | None = None,
        metadata: dict | None = None,
    ) -> RuntimeResult:
        if include_context:
            transcript = (
                list(self._context[-context_window:])
                if context_window is not None and context_window > 0
                else list(self._context)
            )
        else:
            transcript = []
        result = await self.runtime.invoke(
            system_prompt=system_prompt,
            transcript=transcript,
            prompt=content,
            output_schema=output_schema,
            use_native_session=use_native_session,
            cwd=cwd,
            metadata=metadata,
        )
        if record_history:
            self.add_to_context(RuntimeMessage(role="user", content=content))
            self.add_to_context(RuntimeMessage(role="assistant", content=result.content))
        return result

    def export_context(self, name: str) -> Path:
        return self.runtime.export_context(name, self._context)

    def fork(self) -> BaseAgent:
        raise NotImplementedError
