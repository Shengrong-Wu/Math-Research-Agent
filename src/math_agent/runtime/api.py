"""API-backed runtime implementations."""

from __future__ import annotations

import json
from typing import Any

import anthropic
import openai
from google import genai
from google.genai import types

from math_agent.runtime.base import RuntimeBackend, RuntimeInvocation


class APIRuntime(RuntimeBackend):
    """Base runtime for provider SDK backends."""

    supports_native_resume = False

    def is_api_backend(self) -> bool:
        return True

    def _prompt_with_schema(self, invocation: RuntimeInvocation) -> str:
        prompt = invocation.prompt
        if invocation.output_schema is not None:
            prompt += (
                "\n\nReturn valid JSON that matches this schema exactly:\n"
                + json.dumps(invocation.output_schema, indent=2, ensure_ascii=True)
            )
        return prompt

    def _require_api_key(self) -> str:
        if not self.config.api_key:
            raise RuntimeError(
                f"{self.config.backend} backend requires an API key; set the matching environment variable or config api_key."
            )
        return self.config.api_key


class OpenAIRuntime(APIRuntime):
    name = "openai"

    def __init__(self, config):
        super().__init__(config)
        self._client = openai.AsyncOpenAI(api_key=self._require_api_key())

    def _build_input(self, invocation: RuntimeInvocation) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        if invocation.system_prompt:
            items.append({"role": "system", "content": invocation.system_prompt})
        for msg in invocation.transcript:
            items.append({"role": msg.role, "content": msg.content})
        items.append({"role": "user", "content": self._prompt_with_schema(invocation)})
        return items

    async def invoke_api(
        self,
        invocation: RuntimeInvocation,
    ) -> tuple[str, dict[str, Any]]:
        response = await self._client.responses.create(
            model=self.config.model,
            input=self._build_input(invocation),
            temperature=self.config.temperature,
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
        return content, {"provider_usage": usage, "provider_model": response.model}


class AnthropicRuntime(APIRuntime):
    name = "anthropic"

    def __init__(self, config):
        super().__init__(config)
        self._client = anthropic.AsyncAnthropic(api_key=self._require_api_key())

    def _build_messages(self, invocation: RuntimeInvocation) -> list[dict[str, str]]:
        messages = [
            {"role": msg.role, "content": msg.content}
            for msg in invocation.transcript
            if msg.role != "system"
        ]
        messages.append({"role": "user", "content": self._prompt_with_schema(invocation)})
        return messages

    async def invoke_api(
        self,
        invocation: RuntimeInvocation,
    ) -> tuple[str, dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": 8192,
            "messages": self._build_messages(invocation),
            "temperature": self.config.temperature,
        }
        if invocation.system_prompt:
            kwargs["system"] = invocation.system_prompt
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
        return content, {"provider_usage": usage, "provider_model": response.model}


class DeepSeekRuntime(APIRuntime):
    name = "deepseek"
    _BASE_URL = "https://api.deepseek.com"

    def __init__(self, config):
        super().__init__(config)
        self._client = openai.AsyncOpenAI(
            api_key=self._require_api_key(),
            base_url=self._BASE_URL,
        )

    def _build_messages(self, invocation: RuntimeInvocation) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if invocation.system_prompt:
            messages.append({"role": "system", "content": invocation.system_prompt})
        for msg in invocation.transcript:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": self._prompt_with_schema(invocation)})
        return messages

    async def invoke_api(
        self,
        invocation: RuntimeInvocation,
    ) -> tuple[str, dict[str, Any]]:
        response = await self._client.chat.completions.create(
            model=self.config.model,
            messages=self._build_messages(invocation),
            temperature=self.config.temperature,
        )
        choice = response.choices[0]
        content = choice.message.content or ""
        usage: dict[str, int] = {}
        if response.usage:
            usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }
        return content, {"provider_usage": usage, "provider_model": response.model or self.config.model}


class GeminiRuntime(APIRuntime):
    name = "gemini"

    def __init__(self, config):
        super().__init__(config)
        self._client = genai.Client(api_key=self._require_api_key())

    def _build_contents(self, invocation: RuntimeInvocation) -> list[types.Content]:
        role_map = {"user": "user", "assistant": "model"}
        contents: list[types.Content] = []
        for msg in invocation.transcript:
            if msg.role == "system":
                continue
            contents.append(
                types.Content(
                    role=role_map.get(msg.role, "user"),
                    parts=[types.Part.from_text(text=msg.content)],
                )
            )
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=self._prompt_with_schema(invocation))],
            )
        )
        return contents

    def _build_config(self, invocation: RuntimeInvocation) -> types.GenerateContentConfig:
        config = types.GenerateContentConfig(temperature=self.config.temperature)
        if invocation.system_prompt:
            config.system_instruction = invocation.system_prompt
        return config

    async def invoke_api(
        self,
        invocation: RuntimeInvocation,
    ) -> tuple[str, dict[str, Any]]:
        response = await self._client.aio.models.generate_content(
            model=self.config.model,
            contents=self._build_contents(invocation),
            config=self._build_config(invocation),
        )
        content = response.text or ""
        usage: dict[str, int] = {}
        if response.usage_metadata:
            usage = {
                "input_tokens": response.usage_metadata.prompt_token_count or 0,
                "output_tokens": response.usage_metadata.candidates_token_count or 0,
            }
        return content, {"provider_usage": usage, "provider_model": self.config.model}
