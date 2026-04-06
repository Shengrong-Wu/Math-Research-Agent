from __future__ import annotations

import os
from typing import AsyncIterator

from google import genai
from google.genai import types

from .base import BaseLLMClient, LLMMessage, LLMResponse


class GeminiClient(BaseLLMClient):
    """Google Gemini provider using the google-genai SDK."""

    DEFAULT_MODEL = "gemini-2.5-pro"

    def __init__(
        self,
        model: str = "",
        temperature: float = 0.7,
        api_key: str = "",
    ):
        resolved_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        super().__init__(
            model=model or self.DEFAULT_MODEL,
            temperature=temperature,
            api_key=resolved_key,
        )
        self._client = genai.Client(api_key=self.api_key)

    @staticmethod
    def _build_contents(
        messages: list[LLMMessage],
    ) -> list[types.Content]:
        """Convert LLMMessages to genai Content objects.

        System messages are excluded here (they go via the config).
        The genai SDK uses 'user' and 'model' as role names.
        """
        role_map = {"user": "user", "assistant": "model"}
        contents: list[types.Content] = []
        for msg in messages:
            if msg.role == "system":
                continue
            genai_role = role_map.get(msg.role, "user")
            contents.append(
                types.Content(
                    role=genai_role,
                    parts=[types.Part.from_text(text=msg.content)],
                )
            )
        return contents

    def _build_config(self, system: str) -> types.GenerateContentConfig:
        """Build generation config, optionally including a system instruction."""
        config = types.GenerateContentConfig(
            temperature=self.temperature,
        )
        if system:
            config.system_instruction = system
        return config

    async def generate(
        self, messages: list[LLMMessage], system: str = ""
    ) -> LLMResponse:
        """Send messages and get a response via Gemini's generate_content."""
        try:
            response = await self._client.aio.models.generate_content(
                model=self.model,
                contents=self._build_contents(messages),
                config=self._build_config(system),
            )

            content = response.text or ""

            usage: dict[str, int] = {}
            if response.usage_metadata:
                usage = {
                    "input_tokens": response.usage_metadata.prompt_token_count or 0,
                    "output_tokens": response.usage_metadata.candidates_token_count or 0,
                }

            return LLMResponse(
                content=content,
                model=self.model,
                usage=usage,
            )
        except Exception as exc:
            raise RuntimeError(f"Gemini API error: {exc}") from exc

    async def generate_stream(
        self, messages: list[LLMMessage], system: str = ""
    ) -> AsyncIterator[str]:
        """Stream response chunks, yielding text deltas."""
        try:
            async for chunk in self._client.aio.models.generate_content_stream(
                model=self.model,
                contents=self._build_contents(messages),
                config=self._build_config(system),
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as exc:
            raise RuntimeError(f"Gemini API streaming error: {exc}") from exc
