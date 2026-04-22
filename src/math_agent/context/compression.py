"""Progressive context compression."""

from __future__ import annotations

from dataclasses import dataclass

from math_agent.context.token_budget import TokenBudget
from math_agent.runtime import AgentRuntimeSession, RuntimeMessage


@dataclass
class CompressionEvent:
    layer: int
    action: str
    tokens_before: int
    tokens_after: int


class ContextCompressor:
    """4-layer progressive context compression."""

    def __init__(
        self,
        budget: TokenBudget,
        runtime: AgentRuntimeSession | None = None,
    ):
        self.budget = budget
        self.runtime = runtime
        self._events: list[CompressionEvent] = []

    @property
    def events(self) -> list[CompressionEvent]:
        return list(self._events)

    async def compress_if_needed(
        self,
        messages: list[RuntimeMessage],
    ) -> tuple[list[RuntimeMessage], bool]:
        self.budget.update(self._estimate_tokens(messages))
        pressure = self.budget.pressure()
        if pressure.level == "low":
            return messages, False

        result = list(messages)
        if pressure.level in ("moderate", "high", "critical"):
            result = self._layer1_shrink_outputs(result)
            self.budget.update(self._estimate_tokens(result))
            pressure = self.budget.pressure()

        if pressure.level in ("high", "critical"):
            result = self._layer2_snip_old_turns(result)
            self.budget.update(self._estimate_tokens(result))
            pressure = self.budget.pressure()

        if pressure.level == "critical":
            result = await self._layer3_summarize(result)
            self.budget.update(self._estimate_tokens(result))
            pressure = self.budget.pressure()

        if pressure.level == "critical":
            self._events.append(
                CompressionEvent(
                    layer=4,
                    action="full_context_renewal",
                    tokens_before=self._estimate_tokens(messages),
                    tokens_after=0,
                )
            )
            return [], True

        return result, False

    def _layer1_shrink_outputs(self, messages: list[RuntimeMessage]) -> list[RuntimeMessage]:
        result = []
        for msg in messages:
            if msg.role == "assistant" and len(msg.content) > 3000:
                truncated = msg.content[:1500] + "\n\n[... truncated ...]\n\n" + msg.content[-1500:]
                result.append(RuntimeMessage(role=msg.role, content=truncated))
                self._events.append(
                    CompressionEvent(
                        layer=1,
                        action="truncate_long_message",
                        tokens_before=len(msg.content) // 4,
                        tokens_after=len(truncated) // 4,
                    )
                )
            else:
                result.append(msg)
        return result

    def _layer2_snip_old_turns(self, messages: list[RuntimeMessage]) -> list[RuntimeMessage]:
        if len(messages) <= 6:
            return messages

        system_msgs = [m for m in messages[:2] if m.role in ("system", "user")]
        recent = messages[-6:]
        snipped_count = len(messages) - len(system_msgs) - len(recent)
        if snipped_count <= 0:
            return messages

        marker = RuntimeMessage(
            role="user",
            content=f"[{snipped_count} earlier conversation turns removed to save context]",
        )
        result = system_msgs + [marker] + recent
        self._events.append(
            CompressionEvent(
                layer=2,
                action=f"snipped_{snipped_count}_turns",
                tokens_before=self._estimate_tokens(messages),
                tokens_after=self._estimate_tokens(result),
            )
        )
        return result

    async def _layer3_summarize(self, messages: list[RuntimeMessage]) -> list[RuntimeMessage]:
        if len(messages) <= 4:
            return messages

        to_summarize = messages[:-4]
        recent = messages[-4:]
        summary_lines: list[str] = []
        interesting_markers = (
            "proved",
            "verified",
            "failed",
            "gap",
            "lemma",
            "review",
            "falsifier",
            "roadmap",
            "counterexample",
        )
        for msg in to_summarize:
            compact = " ".join(
                line.strip()
                for line in msg.content.splitlines()
                if line.strip()
            )[:280]
            if not compact:
                continue
            lowered = compact.lower()
            if msg.role == "user" or any(marker in lowered for marker in interesting_markers):
                summary_lines.append(f"[{msg.role}] {compact}")
        if not summary_lines:
            summary_lines = [
                f"[{msg.role}] {' '.join(msg.content.split())[:180]}"
                for msg in to_summarize[-6:]
                if msg.content.strip()
            ]

        result = [
            RuntimeMessage(
                role="user",
                content="[Deterministic summary of prior work]\n"
                + "\n".join(summary_lines[-10:]),
            )
        ] + recent

        self._events.append(
            CompressionEvent(
                layer=3,
                action="deterministic_summary",
                tokens_before=self._estimate_tokens(messages),
                tokens_after=self._estimate_tokens(result),
            )
        )
        return result

    @staticmethod
    def _estimate_tokens(messages: list[RuntimeMessage]) -> int:
        chars = sum(len(m.content) for m in messages)
        overhead = 12 * len(messages)
        return (chars + overhead) // 3
