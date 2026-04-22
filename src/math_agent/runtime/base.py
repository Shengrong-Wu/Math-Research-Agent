"""Session-backed runtime abstraction for CLI and API backends."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from abc import ABC
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate

from math_agent.config import RuntimeConfig

logger = logging.getLogger(__name__)

# Codex accepts at most 1 048 576 characters (1 MiB) per request.
# We leave 148 K of headroom for system prompt / CLI flags / framing.
MAX_INPUT_CHARS = 900_000


class InputTooLargeError(RuntimeError):
    """Raised when the prompt payload exceeds the backend's input limit."""

    def __init__(self, actual: int, limit: int = MAX_INPUT_CHARS):
        self.actual = actual
        self.limit = limit
        super().__init__(
            f"Prompt payload is {actual:,} chars, exceeding the "
            f"{limit:,}-char safety limit (backend hard cap ~1 048 576). "
            f"Reduce MEMO/NOTES size or use render_slim() for roadmap "
            f"generation prompts."
        )


class CommandExecutionError(RuntimeError):
    """Raised when the backend CLI exits non-zero."""

    def __init__(
        self,
        returncode: int,
        command: list[str],
        stdout: str,
        stderr: str,
    ) -> None:
        self.returncode = returncode
        self.command = list(command)
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            f"Command failed with exit code {returncode}: {' '.join(command)}\n"
            f"{stderr or stdout}"
        )


@dataclass
class RuntimeMessage:
    role: str
    content: str


@dataclass
class RuntimeResult:
    content: str
    model: str
    backend: str
    session_id: str = ""
    structured_output: Any = None
    stdout: str = ""
    stderr: str = ""
    command: list[str] = field(default_factory=list)
    used_native_resume: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeSessionState:
    role: str
    backend: str
    model: str
    session_id: str = ""
    invocation_count: int = 0
    supports_native_resume: bool = True
    last_invocation_at: str = ""
    workspace: str = ""
    exported_contexts: list[str] = field(default_factory=list)


@dataclass
class RuntimeInvocation:
    role: str
    system_prompt: str
    prompt: str
    transcript: list[RuntimeMessage]
    output_schema: dict[str, Any] | None = None
    use_native_session: bool = True
    cwd: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def render_transcript(messages: list[RuntimeMessage]) -> str:
    """Render transcript to a backend-neutral text block."""

    parts: list[str] = []
    for msg in messages:
        parts.append(f"<{msg.role}>\n{msg.content}\n</{msg.role}>")
    return "\n\n".join(parts)


def extract_json(text: str) -> Any:
    """Best-effort JSON extraction from markdown/codefence wrapped output."""

    stripped = text.strip()
    for pattern in (
        r"```json\s*(.*?)```",
        r"```\s*(.*?)```",
    ):
        match = re.search(pattern, stripped, re.DOTALL)
        if match:
            stripped = match.group(1).strip()
            break

    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(stripped)

    obj_match = re.search(r"(\{.*\}|\[.*\])", stripped, re.DOTALL)
    if obj_match:
        return json.loads(obj_match.group(1))

    raise json.JSONDecodeError("No JSON object found", stripped, 0)


class RuntimeBackend(ABC):
    """Backend-specific command builder or API invoker."""

    name: str
    supports_native_resume: bool = True

    def __init__(self, config: RuntimeConfig):
        self.config = config

    def is_api_backend(self) -> bool:
        return False

    async def invoke_api(
        self,
        invocation: RuntimeInvocation,
    ) -> tuple[str, dict[str, Any]]:
        raise NotImplementedError(f"{self.__class__.__name__} does not implement API invocation")

    def build_fresh_command(
        self,
        invocation: RuntimeInvocation,
        schema_path: Path | None,
    ) -> tuple[list[str], str | None]:
        raise NotImplementedError(f"{self.__class__.__name__} does not implement CLI execution")

    def build_resume_command(
        self,
        invocation: RuntimeInvocation,
        session_id: str,
        schema_path: Path | None,
    ) -> tuple[list[str], str | None]:
        raise NotImplementedError(f"{self.__class__.__name__} does not implement CLI execution")

    def parse_result(
        self,
        stdout: str,
        stderr: str,
        output_schema: dict[str, Any] | None,
    ) -> tuple[str, Any, str]:
        """Return content, structured output, and any discovered session id."""

        content = stdout.strip()
        structured = None
        session_id = self._extract_session_id(stdout) or self._extract_session_id(stderr)

        if output_schema is not None:
            structured = extract_json(content)
            validate(structured, output_schema)
            content = json.dumps(structured, indent=2, ensure_ascii=True)

        return content, structured, session_id

    @staticmethod
    def _extract_session_id(text: str) -> str:
        patterns = (
            r'"session_id"\s*:\s*"([^"]+)"',
            r'"conversation_id"\s*:\s*"([^"]+)"',
            r'"thread_id"\s*:\s*"([^"]+)"',
            r"\bsession(?:\s+id)?[:=]\s*([0-9a-fA-F-]{8,})",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return ""


class AgentRuntimeSession:
    """Durable per-role runtime session with artifact capture."""

    def __init__(
        self,
        *,
        role: str,
        runtime_config: RuntimeConfig,
        backend: RuntimeBackend,
        root_dir: Path,
        workspace: Path,
        seed_messages: list[RuntimeMessage] | None = None,
    ) -> None:
        self.role = role
        self.runtime_config = runtime_config
        self.backend = backend
        self.root_dir = root_dir
        self.workspace = workspace
        self.root_dir.mkdir(parents=True, exist_ok=True)
        (self.root_dir / "invocations").mkdir(exist_ok=True)
        (self.root_dir / "exports").mkdir(exist_ok=True)
        self._state_path = self.root_dir / "session.json"
        self._seed_messages = list(seed_messages or [])
        self._state = self._load_state()
        if not self._state.workspace:
            self._state.workspace = str(workspace)
            self._save_state()
        if not self.backend.supports_native_resume:
            self._state.supports_native_resume = False
            self._state.session_id = ""
            self._save_state()

    @property
    def state(self) -> RuntimeSessionState:
        return RuntimeSessionState(**asdict(self._state))

    def preview_prompt_chars(
        self,
        *,
        system_prompt: str,
        transcript: list[RuntimeMessage],
        prompt: str,
        output_schema: dict[str, Any] | None = None,
        use_native_session: bool | None = None,
        cwd: Path | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        request = RuntimeInvocation(
            role=self.role,
            system_prompt=system_prompt,
            prompt=prompt,
            transcript=[*self._seed_messages, *transcript],
            output_schema=output_schema,
            use_native_session=(
                self.runtime_config.persist_session
                if use_native_session is None
                else use_native_session
            ),
            cwd=cwd or self.workspace,
            metadata=dict(metadata or {}),
        )
        return len(self._render_prompt_payload(request))

    async def invoke(
        self,
        *,
        system_prompt: str,
        transcript: list[RuntimeMessage],
        prompt: str,
        output_schema: dict[str, Any] | None = None,
        use_native_session: bool | None = None,
        cwd: Path | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RuntimeResult:
        invocation_index = self._state.invocation_count + 1
        invocation_dir = self.root_dir / "invocations" / f"{invocation_index:04d}"
        invocation_dir.mkdir(parents=True, exist_ok=True)

        full_transcript = [*self._seed_messages, *transcript]
        request = RuntimeInvocation(
            role=self.role,
            system_prompt=system_prompt,
            prompt=prompt,
            transcript=full_transcript,
            output_schema=output_schema,
            use_native_session=(
                self.runtime_config.persist_session
                if use_native_session is None
                else use_native_session
            ),
            cwd=cwd or self.workspace,
            metadata=dict(metadata or {}),
        )

        schema_path: Path | None = None
        if output_schema is not None:
            schema_path = invocation_dir / "schema.json"
            schema_path.write_text(
                json.dumps(output_schema, indent=2),
                encoding="utf-8",
            )

        prompt_payload = self._render_prompt_payload(request)
        prompt_chars = len(prompt_payload)
        transcript_chars = sum(len(m.content) for m in full_transcript)
        near_limit_threshold = int(
            request.metadata.get("near_limit_chars", MAX_INPUT_CHARS * 0.83)
        )
        prompt_path = invocation_dir / "prompt.md"
        prompt_path.write_text(prompt_payload, encoding="utf-8")
        transcript_path = invocation_dir / "transcript.json"
        transcript_path.write_text(
            json.dumps([asdict(m) for m in full_transcript], indent=2),
            encoding="utf-8",
        )

        content = ""
        structured = None
        discovered_session_id = ""
        stdout = ""
        stderr = ""
        retry_count = 0
        retry_reasons: list[str] = []
        command: list[str] = []
        stdin_payload_chars = 0
        hidden_transcript_chars = 0
        hidden_transcript_share = 0.0
        backend_extra: dict[str, Any] = {}
        use_native_resume = bool(
            request.use_native_session
            and self._state.supports_native_resume
            and self._state.session_id
            and not self.backend.is_api_backend()
        )

        if self.backend.is_api_backend():
            self._state.supports_native_resume = False
            content, backend_extra, retry_count, retry_reasons = await self._invoke_api_with_retries(
                request,
                invocation_dir=invocation_dir,
            )
            stdout = str(backend_extra.get("stdout", ""))
            stderr = str(backend_extra.get("stderr", ""))
            discovered_session_id = str(backend_extra.get("session_id", ""))
        else:
            command, stdin_payload = (
                self.backend.build_resume_command(
                    request,
                    self._state.session_id,
                    schema_path,
                )
                if use_native_resume
                else self.backend.build_fresh_command(request, schema_path)
            )
            stdin_payload_chars = len(stdin_payload or "")
            hidden_transcript_chars = transcript_chars if use_native_resume else 0
            hidden_transcript_share = (
                transcript_chars / prompt_chars
                if use_native_resume and prompt_chars > 0
                else 0.0
            )

            stdout, stderr, retry_count, retry_reasons = await self._run_with_retries(
                command,
                cwd=request.cwd,
                stdin_input=stdin_payload,
                invocation_dir=invocation_dir,
            )
            content, structured, discovered_session_id = self.backend.parse_result(
                stdout,
                stderr,
                output_schema,
            )

        stdout_path = invocation_dir / "stdout.log"
        stderr_path = invocation_dir / "stderr.log"
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")

        if output_schema is not None and structured is None:
            try:
                structured = extract_json(content)
                validate(structured, output_schema)
                content = json.dumps(structured, indent=2, ensure_ascii=True)
            except (ValidationError, json.JSONDecodeError):
                structured = None

        if request.use_native_session and self.backend.supports_native_resume:
            if discovered_session_id:
                self._state.session_id = discovered_session_id
            elif not use_native_resume:
                self._state.supports_native_resume = False
        else:
            self._state.session_id = ""
            self._state.supports_native_resume = False

        self._state.invocation_count = invocation_index
        self._state.last_invocation_at = datetime.now(timezone.utc).isoformat()
        self._save_state()

        prompt_token_estimate = self._estimate_text_tokens(prompt_payload)
        transcript_token_estimate = self._estimate_text_tokens(
            render_transcript(full_transcript)
        )
        result = RuntimeResult(
            content=content,
            model=self.runtime_config.model,
            backend=self.runtime_config.backend,
            session_id=self._state.session_id,
            structured_output=structured,
            stdout=stdout,
            stderr=stderr,
            command=command,
            used_native_resume=use_native_resume,
            metadata={
                "invocation_dir": str(invocation_dir),
                "workspace": str(request.cwd),
                "role": self.role,
                "callsite": request.metadata.get("callsite", ""),
                "prompt_chars": prompt_chars,
                "reconstructed_prompt_chars": prompt_chars,
                "stdin_payload_chars": stdin_payload_chars,
                "transcript_chars": transcript_chars,
                "hidden_transcript_chars": hidden_transcript_chars,
                "hidden_transcript_share": hidden_transcript_share,
                "prompt_token_estimate": prompt_token_estimate,
                "transcript_token_estimate": transcript_token_estimate,
                "document_char_counts": request.metadata.get("document_char_counts", {}),
                "transcript_char_counts": request.metadata.get("transcript_char_counts", {}),
                "used_fresh_replay": not use_native_resume,
                "near_limit": prompt_chars >= near_limit_threshold,
                "stdin_near_limit": stdin_payload_chars >= near_limit_threshold,
                "hidden_context_pressure": bool(
                    use_native_resume
                    and hidden_transcript_chars >= near_limit_threshold * 0.6
                ),
                "retry_count": retry_count,
                "retry_reasons": retry_reasons,
                **{
                    k: v
                    for k, v in request.metadata.items()
                    if k
                    not in {
                        "callsite",
                        "document_char_counts",
                        "transcript_char_counts",
                        "near_limit_chars",
                    }
                },
                **backend_extra,
            },
        )

        result_path = invocation_dir / "result.json"
        result_path.write_text(
            json.dumps(
                {
                    "content": result.content,
                    "model": result.model,
                    "backend": result.backend,
                    "session_id": result.session_id,
                    "used_native_resume": result.used_native_resume,
                    "structured_output": result.structured_output,
                    "metadata": result.metadata,
                    "command": result.command,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info(
            "Runtime[%s] callsite=%s prompt=%d (~%d tok) transcript=%d (~%d tok) replay=%s retries=%d tier=%s",
            self.role,
            result.metadata.get("callsite", ""),
            prompt_chars,
            prompt_token_estimate,
            transcript_chars,
            transcript_token_estimate,
            "fresh" if result.metadata.get("used_fresh_replay") else "native",
            retry_count,
            result.metadata.get("assembly_profile", ""),
        )
        return result

    async def _invoke_api_with_retries(
        self,
        request: RuntimeInvocation,
        *,
        invocation_dir: Path,
    ) -> tuple[str, dict[str, Any], int, list[str]]:
        retry_reasons: list[str] = []
        max_attempts = max(1, self.runtime_config.max_retries + 1)
        backoff_ms = max(0, self.runtime_config.retry_backoff_ms)

        for attempt in range(1, max_attempts + 1):
            try:
                content, meta = await self.backend.invoke_api(request)
                return content, meta, attempt - 1, retry_reasons
            except Exception as exc:
                self._record_attempt_failure(invocation_dir, attempt, exc)
                retry_reason = self._classify_retry_reason(exc)
                if retry_reason is None or attempt >= max_attempts:
                    raise
                retry_reasons.append(retry_reason)
                delay_ms = backoff_ms * (2 ** (attempt - 1))
                jitter_ms = random.randint(0, max(100, backoff_ms // 2))
                await asyncio.sleep((delay_ms + jitter_ms) / 1000.0)

        raise AssertionError("unreachable")

    async def _run_with_retries(
        self,
        command: list[str],
        *,
        cwd: Path | None,
        stdin_input: str | None,
        invocation_dir: Path,
    ) -> tuple[str, str, int, list[str]]:
        retry_reasons: list[str] = []
        max_attempts = max(1, self.runtime_config.max_retries + 1)
        backoff_ms = max(0, self.runtime_config.retry_backoff_ms)

        for attempt in range(1, max_attempts + 1):
            try:
                stdout, stderr = await self._run_command(
                    command,
                    cwd=cwd,
                    stdin_input=stdin_input,
                )
                return stdout, stderr, attempt - 1, retry_reasons
            except Exception as exc:
                self._record_attempt_failure(invocation_dir, attempt, exc)
                retry_reason = self._classify_retry_reason(exc)
                if retry_reason is None or attempt >= max_attempts:
                    raise
                retry_reasons.append(retry_reason)
                delay_ms = backoff_ms * (2 ** (attempt - 1))
                jitter_ms = random.randint(0, max(100, backoff_ms // 2))
                await asyncio.sleep((delay_ms + jitter_ms) / 1000.0)

        raise AssertionError("unreachable")

    @staticmethod
    def _record_attempt_failure(
        invocation_dir: Path,
        attempt: int,
        exc: Exception,
    ) -> None:
        attempts_dir = invocation_dir / "attempts"
        attempts_dir.mkdir(exist_ok=True)
        base = attempts_dir / f"{attempt:02d}"
        if isinstance(exc, CommandExecutionError):
            (base.with_suffix(".stdout.log")).write_text(exc.stdout, encoding="utf-8")
            (base.with_suffix(".stderr.log")).write_text(exc.stderr, encoding="utf-8")
        else:
            (base.with_suffix(".stderr.log")).write_text(str(exc), encoding="utf-8")

    @staticmethod
    def _classify_retry_reason(exc: Exception) -> str | None:
        if isinstance(exc, InputTooLargeError):
            return None
        haystack = str(exc).lower()
        if isinstance(exc, CommandExecutionError):
            haystack = "\n".join(
                [haystack, exc.stdout.lower(), exc.stderr.lower()]
            )
        patterns = (
            ("rate_limit", ("rate limit", "too many requests", "429")),
            ("timeout", ("timed out", "timeout", "deadline exceeded")),
            (
                "transport",
                (
                    "connection reset",
                    "connection aborted",
                    "econnreset",
                    "broken pipe",
                    "network error",
                ),
            ),
            ("capacity", ("at capacity", "model is at capacity", "selected model is at capacity")),
            (
                "backend_overload",
                (
                    "temporarily unavailable",
                    "try again",
                    "overloaded",
                    "503",
                    "502",
                    "500",
                    "bad gateway",
                    "service unavailable",
                ),
            ),
            ("empty_output", ("no output",)),
        )
        for label, needles in patterns:
            if any(needle in haystack for needle in needles):
                return label
        return None

    @staticmethod
    def _estimate_text_tokens(text: str) -> int:
        if not text:
            return 0
        return max(1, (len(text) + 2) // 3)

    def invalidate_session(self) -> None:
        """Drop the native CLI session id so the next invocation starts fresh."""

        self._state.session_id = ""
        self._save_state()

    def export_context(self, name: str, messages: list[RuntimeMessage]) -> Path:
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-") or "context"
        target = self.root_dir / "exports" / f"{slug}.json"
        payload = {
            "role": self.role,
            "backend": self.runtime_config.backend,
            "model": self.runtime_config.model,
            "messages": [asdict(m) for m in messages],
        }
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if str(target) not in self._state.exported_contexts:
            self._state.exported_contexts.append(str(target))
            self._save_state()
        return target

    def fork(
        self,
        *,
        role: str,
        root_dir: Path,
        workspace: Path | None = None,
        seed_messages: list[RuntimeMessage] | None = None,
        runtime_config: RuntimeConfig | None = None,
        backend: RuntimeBackend | None = None,
    ) -> AgentRuntimeSession:
        return AgentRuntimeSession(
            role=role,
            runtime_config=runtime_config or self.runtime_config,
            backend=backend or self.backend,
            root_dir=root_dir,
            workspace=workspace or self.workspace,
            seed_messages=seed_messages,
        )

    def _load_state(self) -> RuntimeSessionState:
        if self._state_path.exists():
            try:
                return RuntimeSessionState(
                    **json.loads(self._state_path.read_text(encoding="utf-8"))
                )
            except (json.JSONDecodeError, OSError, TypeError):
                pass
        return RuntimeSessionState(
            role=self.role,
            backend=self.runtime_config.backend,
            model=self.runtime_config.model,
            workspace=str(self.workspace),
        )

    def _save_state(self) -> None:
        self._state_path.write_text(
            json.dumps(asdict(self._state), indent=2),
            encoding="utf-8",
        )

    @staticmethod
    async def _run_command(
        command: list[str],
        cwd: Path | None,
        stdin_input: str | None = None,
    ) -> tuple[str, str]:
        """Spawn *command* and collect stdout/stderr."""

        if stdin_input is not None and len(stdin_input) > MAX_INPUT_CHARS:
            raise InputTooLargeError(len(stdin_input))

        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd) if cwd else None,
            stdin=asyncio.subprocess.PIPE if stdin_input is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        input_bytes = (
            stdin_input.encode("utf-8")
            if stdin_input is not None
            else None
        )
        stdout_bytes, stderr_bytes = await proc.communicate(input=input_bytes)
        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")
        if proc.returncode != 0:
            raise CommandExecutionError(
                proc.returncode,
                command,
                stdout,
                stderr,
            )
        return stdout, stderr

    @staticmethod
    def _render_prompt_payload(request: RuntimeInvocation) -> str:
        sections = [f"# Role\n{request.role}"]
        if request.system_prompt:
            sections.append(f"# System Prompt\n{request.system_prompt}")
        if request.transcript:
            sections.append(f"# Transcript\n{render_transcript(request.transcript)}")
        sections.append(f"# Current User Prompt\n{request.prompt}")
        if request.output_schema is not None:
            sections.append(
                "# Output Schema\n"
                + json.dumps(request.output_schema, indent=2, ensure_ascii=True)
            )
        return "\n\n".join(sections) + "\n"
