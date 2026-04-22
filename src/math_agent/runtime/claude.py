"""Claude Code runtime backend."""

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


def _permission_mode(policy: str) -> str:
    normalized = (policy or "").strip().lower()
    return {
        "never": "auto",
        "bypass": "bypassPermissions",
        "plan": "plan",
        "on-request": "default",
    }.get(normalized, "default")


class ClaudeRuntime(RuntimeBackend):
    name = "claude"

    def build_fresh_command(
        self,
        invocation: RuntimeInvocation,
        schema_path: Path | None,
    ) -> tuple[list[str], str | None]:
        prompt = self._build_prompt(invocation)
        command = [
            self.config.cli_path or "claude",
            "-p",
            "--output-format",
            "json",
            "--model",
            self.config.model,
            "--permission-mode",
            _permission_mode(self.config.approval_policy),
        ]
        if not invocation.use_native_session:
            command.append("--no-session-persistence")
        if self.config.effort:
            command.extend(["--effort", self.config.effort])
        if invocation.cwd:
            # Use `--add-dir=<path>` form: the claude CLI declares --add-dir as
            # variadic (`<directories...>`), so the space form would greedily
            # consume whatever comes after it on argv.
            command.append(f"--add-dir={invocation.cwd}")
        if schema_path is not None:
            command.extend(["--json-schema", schema_path.read_text(encoding="utf-8")])
        # NOTE: we deliberately do NOT append *prompt* to argv — it goes on
        # stdin instead (see RuntimeBackend docstring). Large review prompts
        # (compiled proof + transcript) can easily exceed POSIX ARG_MAX
        # (~1 MiB on macOS) and crash execve with "Argument list too long".
        # `claude -p` with no positional argument reads the prompt from stdin.
        return command, prompt

    def build_resume_command(
        self,
        invocation: RuntimeInvocation,
        session_id: str,
        schema_path: Path | None,
    ) -> tuple[list[str], str | None]:
        command = [
            self.config.cli_path or "claude",
            "-p",
            "-r",
            session_id,
            "--output-format",
            "json",
            "--model",
            self.config.model,
            "--permission-mode",
            _permission_mode(self.config.approval_policy),
        ]
        if self.config.effort:
            command.extend(["--effort", self.config.effort])
        if invocation.cwd:
            # See note in build_fresh_command: --add-dir is variadic in the CLI.
            command.append(f"--add-dir={invocation.cwd}")
        if schema_path is not None:
            command.extend(["--json-schema", schema_path.read_text(encoding="utf-8")])
        # Prompt goes on stdin — see build_fresh_command for rationale.
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
        if not stdout.strip():
            raise RuntimeError(
                "Claude returned empty stdout. Check `claude` authentication and CLI health."
            )

        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return super().parse_result(stdout, stderr, output_schema)

        if not isinstance(payload, dict):
            return super().parse_result(stdout, stderr, output_schema)

        session_id = str(payload.get("session_id", "") or "")
        raw_result = payload.get("result", "")
        if payload.get("is_error"):
            raise RuntimeError(str(raw_result or stderr or stdout).strip())

        if output_schema is None:
            if isinstance(raw_result, str):
                return raw_result.strip(), None, session_id
            return json.dumps(raw_result, indent=2, ensure_ascii=True), raw_result, session_id

        structured = raw_result
        if not isinstance(structured, (dict, list)):
            structured = extract_json(str(raw_result))
        validate(structured, output_schema)
        content = json.dumps(structured, indent=2, ensure_ascii=True)
        return content, structured, session_id
