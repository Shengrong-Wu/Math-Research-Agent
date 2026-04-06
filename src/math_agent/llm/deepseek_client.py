from __future__ import annotations

import os
from typing import AsyncIterator

import openai

from .base import BaseLLMClient, LLMMessage, LLMResponse


class DeepSeekClient(BaseLLMClient):
    """DeepSeek provider using the OpenAI SDK with a custom base URL."""

    DEFAULT_MODEL = "deepseek-reasoner"
    BASE_URL = "https://api.deepseek.com"

    def __init__(
        self,
        model: str = "",
        temperature: float = 0.7,
        api_key: str = "",
    ):
        resolved_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        super().__init__(
            model=model or self.DEFAULT_MODEL,
            temperature=temperature,
            api_key=resolved_key,
        )
        self._client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.BASE_URL,
        )

    @staticmethod
    def _build_messages(
        messages: list[LLMMessage], system: str
    ) -> list[dict[str, str]]:
        """Convert LLMMessages with system message prepended to the messages list."""
        msgs: list[dict[str, str]] = []
        if system:
            msgs.append({"role": "system", "content": system})
        for msg in messages:
            msgs.append({"role": msg.role, "content": msg.content})
        return msgs

    async def generate(
        self, messages: list[LLMMessage], system: str = ""
    ) -> LLMResponse:
        """Send messages and get a response via the OpenAI-compatible chat API."""
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=self._build_messages(messages, system),
                temperature=self.temperature,
            )

            choice = response.choices[0]
            content = choice.message.content or ""

            usage: dict[str, int] = {}
            if response.usage:
                usage = {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens,
                }

            return LLMResponse(
                content=content,
                model=response.model or self.model,
                usage=usage,
            )
        except openai.APIError as exc:
            raise RuntimeError(f"DeepSeek API error: {exc}") from exc

    async def generate_stream(
        self, messages: list[LLMMessage], system: str = ""
    ) -> AsyncIterator[str]:
        """Stream response chunks, yielding text deltas."""
        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=self._build_messages(messages, system),
                temperature=self.temperature,
                stream=True,
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except openai.APIError as exc:
            raise RuntimeError(f"DeepSeek API streaming error: {exc}") from exc
