from __future__ import annotations

import os
from typing import AsyncIterator

import openai

from .base import BaseLLMClient, LLMMessage, LLMResponse


class OpenAIClient(BaseLLMClient):
    """OpenAI provider using the Responses API."""

    DEFAULT_MODEL = "o3"

    def __init__(
        self,
        model: str = "",
        temperature: float = 0.7,
        api_key: str = "",
    ):
        resolved_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        super().__init__(
            model=model or self.DEFAULT_MODEL,
            temperature=temperature,
            api_key=resolved_key,
        )
        self._client = openai.AsyncOpenAI(api_key=self.api_key)

    def _build_input(
        self, messages: list[LLMMessage], system: str
    ) -> list[dict[str, str]]:
        """Convert LLMMessages to the OpenAI input format."""
        input_msgs: list[dict[str, str]] = []
        if system:
            input_msgs.append({"role": "system", "content": system})
        for msg in messages:
            input_msgs.append({"role": msg.role, "content": msg.content})
        return input_msgs

    async def generate(
        self, messages: list[LLMMessage], system: str = ""
    ) -> LLMResponse:
        """Send messages and get a response via the Responses API."""
        try:
            response = await self._client.responses.create(
                model=self.model,
                input=self._build_input(messages, system),
                temperature=self.temperature,
            )

            content = ""
            for item in response.output:
                if item.type == "message":
                    for block in item.content:
                        if block.type == "output_text":
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
        except openai.APIError as exc:
            raise RuntimeError(f"OpenAI API error: {exc}") from exc

    async def generate_stream(
        self, messages: list[LLMMessage], system: str = ""
    ) -> AsyncIterator[str]:
        """Stream response chunks, yielding text deltas."""
        try:
            stream = await self._client.responses.create(
                model=self.model,
                input=self._build_input(messages, system),
                temperature=self.temperature,
                stream=True,
            )

            async for event in stream:
                if (
                    event.type == "response.output_text.delta"
                    and hasattr(event, "delta")
                ):
                    yield event.delta
        except openai.APIError as exc:
            raise RuntimeError(f"OpenAI API streaming error: {exc}") from exc
