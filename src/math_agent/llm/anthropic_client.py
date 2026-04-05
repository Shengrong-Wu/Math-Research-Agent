from __future__ import annotations

import os
from typing import AsyncIterator

import anthropic

from .base import BaseLLMClient, LLMMessage, LLMResponse


class AnthropicClient(BaseLLMClient):
    """Anthropic provider using the Messages API."""

    DEFAULT_MODEL = "claude-opus-4-0626"

    def __init__(
        self,
        model: str = "",
        temperature: float = 0.7,
        api_key: str = "",
    ):
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        super().__init__(
            model=model or self.DEFAULT_MODEL,
            temperature=temperature,
            api_key=resolved_key,
        )
        self._client = anthropic.AsyncAnthropic(api_key=self.api_key)

    @staticmethod
    def _build_messages(messages: list[LLMMessage]) -> list[dict[str, str]]:
        """Convert LLMMessages, filtering out system messages (handled separately)."""
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
            if msg.role != "system"
        ]

    async def generate(
        self, messages: list[LLMMessage], system: str = ""
    ) -> LLMResponse:
        """Send messages and get a response. System message goes in the system parameter."""
        try:
            kwargs: dict = {
                "model": self.model,
                "max_tokens": 8192,
                "messages": self._build_messages(messages),
                "temperature": self.temperature,
            }
            if system:
                kwargs["system"] = system

            response = await self._client.messages.create(**kwargs)

            content = ""
            for block in response.content:
                if block.type == "text":
                    content += block.text

            usage: dict[str, int] = {}
            if response.usage:
                usage = {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                }

            return LLMResponse(
                content=content,
                model=response.model,
                usage=usage,
            )
        except anthropic.APIError as exc:
            raise RuntimeError(f"Anthropic API error: {exc}") from exc

    async def generate_stream(
        self, messages: list[LLMMessage], system: str = ""
    ) -> AsyncIterator[str]:
        """Stream response chunks using client.messages.stream()."""
        try:
            kwargs: dict = {
                "model": self.model,
                "max_tokens": 8192,
                "messages": self._build_messages(messages),
                "temperature": self.temperature,
            }
            if system:
                kwargs["system"] = system

            async with self._client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text
        except anthropic.APIError as exc:
            raise RuntimeError(f"Anthropic API streaming error: {exc}") from exc
