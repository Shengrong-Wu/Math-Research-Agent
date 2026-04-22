"""Codex runtime backend."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate

from math_agent.runtime.base import (
    RuntimeBackend,
    RuntimeInvocation,
    extract_json,
    render_transcript,
)


class CodexRuntime(RuntimeBackend):
    name = "codex"

    def build_fresh_command(
        self,
        invocation: RuntimeInvocation,
        schema_path: Path | None,
    ) -> tuple[list[str], str | None]:
        command = [self.config.cli_path or "codex"]
        if self.config.approval_policy:
            command.extend(["--ask-for-approval", self.config.approval_policy])
        command.extend(
            [
                "exec",
                "--skip-git-repo-check",
                "--json",
                "--sandbox",
                self.config.sandbox,
            ]
        )
        if self.config.model:
            command.extend(["--model", self.config.model])
        if self.config.profile:
            command.extend(["--profile", self.config.profile])
        if self.config.effort:
            command.extend(["-c", f'reasoning_effort="{self.config.effort}"'])
        if invocation.cwd:
            command.extend(["--cd", str(invocation.cwd)])
            command.extend(["--add-dir", str(invocation.cwd)])
        if schema_path is not None:
            command.extend(["--output-schema", str(schema_path)])
        # Prompt goes on stdin rather than argv — see RuntimeBackend docstring.
        # `codex exec` with no [PROMPT] positional reads instructions from
        # stdin automatically, so we do not need an explicit `-` sentinel.
        return command, self._build_prompt(invocation)

    def build_resume_command(
        self,
        invocation: RuntimeInvocation,
        session_id: str,
        schema_path: Path | None,
    ) -> tuple[list[str], str | None]:
        command = [self.config.cli_path or "codex"]
        if self.config.approval_policy:
            command.extend(["--ask-for-approval", self.config.approval_policy])
        command.extend(
            [
                "exec",
                "resume",
                session_id,
                "--skip-git-repo-check",
                "--json",
            ]
        )
        if self.config.model:
            command.extend(["--model", self.config.model])
        if self.config.effort:
            command.extend(["-c", f'reasoning_effort="{self.config.effort}"'])
        if schema_path is not None:
            command.extend(["--output-schema", str(schema_path)])
        # `codex exec resume` only reads from stdin when the PROMPT argument
        # is the explicit sentinel `-`; unlike the fresh subcommand it does
        # NOT auto-detect stdin when the positional is omitted.
        command.append("-")
        return command, invocation.prompt

    @staticmethod
    def _build_prompt(invocation: RuntimeInvocation) -> str:
        parts: list[str] = []
        if invocation.system_prompt:
            parts.append(f"System instructions:\n{invocation.system_prompt}")
        if invocation.transcript:
            parts.append(
                "Prior conversation transcript:\n"
                + render_transcript(invocation.transcript)
            )
        parts.append(f"Current task:\n{invocation.prompt}")
        if invocation.output_schema is not None:
            parts.append(
                "Return valid JSON that matches the provided schema exactly."
            )
        return "\n\n".join(parts)

    def parse_result(
        self,
        stdout: str,
        stderr: str,
        output_schema: dict | None,
    ) -> tuple[str, object | None, str]:
        events = self._load_jsonl(stdout)
        session_id = ""
        candidates: list[object] = []

        for event in events:
            if not session_id:
                session_id = str(
                    event.get("thread_id")
                    or event.get("session_id")
                    or event.get("conversation_id")
                    or ""
                )
            candidates.extend(self._collect_preferred_candidates(event))

        if not candidates:
            for event in events:
                candidates.extend(self._collect_candidates(event))

        if output_schema is not None:
            for candidate in reversed(candidates):
                try:
                    structured = candidate
                    if not isinstance(structured, (dict, list)):
                        structured = extract_json(str(candidate))
                    validate(structured, output_schema)
                    return (
                        json.dumps(structured, indent=2, ensure_ascii=True),
                        structured,
                        session_id,
                    )
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
            return super().parse_result(stdout, stderr, output_schema)

        for candidate in reversed(candidates):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip(), None, session_id
            if isinstance(candidate, (dict, list)):
                content = json.dumps(candidate, indent=2, ensure_ascii=True)
                return content, candidate, session_id

        return super().parse_result(stdout, stderr, output_schema)

    @staticmethod
    def _load_jsonl(stdout: str) -> list[dict]:
        events: list[dict] = []
        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped.startswith("{"):
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
        return events

    @classmethod
    def _collect_preferred_candidates(cls, event: dict) -> list[object]:
        candidates: list[object] = []
        event_type = event.get("type")

        if event_type == "item.completed":
            item = event.get("item", {})
            if isinstance(item, dict):
                item_type = item.get("type")
                if item_type == "agent_message" and isinstance(item.get("text"), str):
                    text = item["text"].strip()
                    if text:
                        candidates.append(text)
                if item_type in {"assistant_message", "message"}:
                    candidates.extend(cls._collect_candidates(item))

        for key in ("final_output", "last_message", "output_text", "result"):
            if key in event:
                candidates.extend(cls._collect_candidates(event[key]))

        return candidates

    @classmethod
    def _collect_candidates(cls, value: object) -> list[object]:
        candidates: list[object] = []
        if isinstance(value, str):
            if value.strip():
                candidates.append(value)
            return candidates
        if isinstance(value, list):
            for item in value:
                candidates.extend(cls._collect_candidates(item))
            return candidates
        if not isinstance(value, dict):
            return candidates

        for key in ("result", "content", "text", "message", "output_text", "last_message", "final_output"):
            if key in value:
                candidates.extend(cls._collect_candidates(value[key]))
        for nested in value.values():
            candidates.extend(cls._collect_candidates(nested))
        return candidates
