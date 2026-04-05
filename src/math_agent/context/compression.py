from __future__ import annotations
from dataclasses import dataclass
from math_agent.llm.base import BaseLLMClient, LLMMessage
from math_agent.context.token_budget import TokenBudget, ContextPressure

@dataclass
class CompressionEvent:
    """Record of a compression action taken."""
    layer: int  # 1-4
    action: str
    tokens_before: int
    tokens_after: int

class ContextCompressor:
    """4-layer progressive context compression.

    Layer 1: Shrink large tool outputs and verbose reasoning (>60% capacity)
    Layer 2: Snip old turns - drop early failed attempts (>75% capacity)
    Layer 3: Summarize old proof attempts into MEMO-style entries (>85% capacity)
    Layer 4: Full context renewal - start fresh, read MEMO (>95% capacity, last resort)
    """

    def __init__(self, budget: TokenBudget, client: BaseLLMClient | None = None):
        self.budget = budget
        self.client = client  # needed for layer 3 (summarization)
        self._events: list[CompressionEvent] = []

    @property
    def events(self) -> list[CompressionEvent]:
        return list(self._events)

    async def compress_if_needed(self, messages: list[LLMMessage]) -> tuple[list[LLMMessage], bool]:
        """Apply compression layers as needed. Returns (compressed_messages, was_reset).

        was_reset is True only if layer 4 (full renewal) was triggered.
        """
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

        if pressure.level == "critical" and self.client is not None:
            result = await self._layer3_summarize(result)
            self.budget.update(self._estimate_tokens(result))
            pressure = self.budget.pressure()

        if pressure.level == "critical":
            # Layer 4: full context renewal
            self._events.append(CompressionEvent(
                layer=4, action="full_context_renewal",
                tokens_before=self.budget.pressure().used_tokens,
                tokens_after=0,
            ))
            return [], True  # caller must rebuild from MEMO

        return result, False

    def _layer1_shrink_outputs(self, messages: list[LLMMessage]) -> list[LLMMessage]:
        """Truncate long assistant messages (keep first and last 500 chars)."""
        result = []
        for msg in messages:
            if msg.role == "assistant" and len(msg.content) > 3000:
                truncated = msg.content[:1500] + "\n\n[... truncated ...]\n\n" + msg.content[-1500:]
                result.append(LLMMessage(role=msg.role, content=truncated))
                self._events.append(CompressionEvent(
                    layer=1, action="truncate_long_message",
                    tokens_before=len(msg.content) // 4,
                    tokens_after=len(truncated) // 4,
                ))
            else:
                result.append(msg)
        return result

    def _layer2_snip_old_turns(self, messages: list[LLMMessage]) -> list[LLMMessage]:
        """Remove early conversation turns, keeping the system message and recent turns."""
        if len(messages) <= 6:
            return messages

        # Keep first message (system/problem) and last 6 messages
        system_msgs = [m for m in messages[:2] if m.role in ("system", "user")]
        recent = messages[-6:]
        snipped_count = len(messages) - len(system_msgs) - len(recent)

        if snipped_count > 0:
            marker = LLMMessage(
                role="user",
                content=f"[{snipped_count} earlier conversation turns removed to save context]",
            )
            result = system_msgs + [marker] + recent
            self._events.append(CompressionEvent(
                layer=2, action=f"snipped_{snipped_count}_turns",
                tokens_before=self._estimate_tokens(messages),
                tokens_after=self._estimate_tokens(result),
            ))
            return result
        return messages

    async def _layer3_summarize(self, messages: list[LLMMessage]) -> list[LLMMessage]:
        """Use LLM to summarize old proof attempts."""
        if self.client is None or len(messages) <= 4:
            return messages

        # Summarize everything except the last 4 messages
        to_summarize = messages[:-4]
        recent = messages[-4:]

        summary_text = "\n\n".join(f"[{m.role}]: {m.content[:500]}" for m in to_summarize)

        summary_response = await self.client.generate(
            messages=[LLMMessage(
                role="user",
                content=f"Summarize these proof conversation turns into a concise summary preserving key results, failures, and proved propositions:\n\n{summary_text}",
            )],
            system="You are a mathematical proof assistant. Summarize concisely, preserving all proved results and failure reasons.",
        )

        result = [
            LLMMessage(role="user", content=f"[Summary of prior work]\n{summary_response.content}"),
        ] + recent

        self._events.append(CompressionEvent(
            layer=3, action="summarized_old_turns",
            tokens_before=self._estimate_tokens(messages),
            tokens_after=self._estimate_tokens(result),
        ))
        return result

    @staticmethod
    def _estimate_tokens(messages: list[LLMMessage]) -> int:
        """Rough token estimate (4 chars per token)."""
        return sum(len(m.content) for m in messages) // 4
