from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from math_agent.config import AppConfig, default_cli_path, load_config, resolve_agent_runtime
from math_agent.runtime import AgentRuntimeSession, RuntimeInvocation, RuntimeMessage, build_role_sessions
from math_agent.runtime.base import CommandExecutionError, RuntimeBackend
from math_agent.runtime.claude import ClaudeRuntime
from math_agent.runtime.codex import CodexRuntime
from math_agent.runtime.factory import build_backend


def test_load_runtime_config_and_prompt_budgets(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[hyperparameters]
n_min = 4
n_max = 9

[runtime]
backend = "codex"
model = "gpt-5.4"
effort = "medium"

[prompt_budgets]
roadmap_generation = 11111
review = 2222

[agents.review]
backend = "claude"
model = "sonnet"
effort = "high"

[agents.formalizer]
backend = "codex"
model = "gpt-5.4-mini"
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)
    assert config.runtime.backend == "codex"
    assert config.runtime.model == "gpt-5.4"
    assert config.prompt_budgets.roadmap_generation == 11111
    assert config.prompt_budgets.review == 2222
    resolved_review = resolve_agent_runtime(config.agents.review, config.runtime)
    assert resolved_review.backend == "claude"
    assert resolved_review.model == "sonnet"
    assert resolved_review.effort == "high"
    assert resolved_review.cli_path == default_cli_path("claude")
    resolved_formalizer = resolve_agent_runtime(config.agents.formalizer, config.runtime)
    assert resolved_formalizer.backend == "codex"
    assert resolved_formalizer.model == "gpt-5.4-mini"


def test_load_config_accepts_legacy_provider_alias_and_skip_lean_false(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[hyperparameters]
skip_lean = false

[provider]
name = "openai"
model = "o3"

[agents.review]
name = "claude"
model = "sonnet"
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)
    assert config.runtime.backend == "openai"
    assert config.runtime.model == "o3"
    assert config.lean_mode == "check"
    resolved_review = resolve_agent_runtime(config.agents.review, config.runtime)
    assert resolved_review.backend == "claude"
    assert resolved_review.cli_path == default_cli_path("claude")


def test_load_config_warns_on_full_and_legacy_agents_cli(tmp_path: Path, caplog):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[hyperparameters]
lean_mode = "full"

[agents.cli]
backend = "claude"
""".strip(),
        encoding="utf-8",
    )

    with caplog.at_level("WARNING"):
        config = load_config(config_path)

    assert config.lean_mode == "check"
    assert "lean_mode=full" in caplog.text
    assert "Ignoring legacy [agents.cli]" in caplog.text


def test_build_role_sessions_uses_only_active_v3_roles(tmp_path: Path):
    config = AppConfig()
    sessions = build_role_sessions(
        config,
        tmp_path / "agent_runtime",
        default_workspace=tmp_path / "workspace",
    )
    assert set(sessions) == {"thinking", "formalizer", "assistant", "review", "falsifier"}


def test_claude_command_builds_resume_and_schema(tmp_path: Path):
    backend = ClaudeRuntime(
        resolve_agent_runtime(load_config().agents.thinking, load_config().runtime)
    )
    invocation = RuntimeInvocation(
        role="thinking",
        system_prompt="system",
        prompt="prove this",
        transcript=[RuntimeMessage(role="user", content="hello")],
    )
    schema = tmp_path / "schema.json"
    schema.write_text('{"type":"object"}', encoding="utf-8")

    fresh, fresh_stdin = backend.build_fresh_command(invocation, schema)
    resumed, resumed_stdin = backend.build_resume_command(invocation, "session-123", schema)
    assert fresh[1:4] == ["-p", "--output-format", "json"]
    assert "--json-schema" in fresh
    assert resumed[1:5] == ["-p", "-r", "session-123", "--output-format"]
    assert fresh_stdin is not None and invocation.prompt in fresh_stdin
    assert resumed_stdin == invocation.prompt
    assert invocation.prompt not in " ".join(fresh)
    assert invocation.prompt not in " ".join(resumed)


def test_codex_command_builds_json_schema(tmp_path: Path):
    config = load_config()
    runtime = resolve_agent_runtime(config.agents.thinking, config.runtime)
    runtime = runtime.__class__(
        backend="codex",
        model="gpt-5.4",
        effort="high",
        profile="",
        sandbox="workspace-write",
        approval_policy="on-request",
        persist_session=True,
        workspace_mode="shared",
        cli_path="codex",
    )
    backend = CodexRuntime(runtime)
    invocation = RuntimeInvocation(
        role="thinking",
        system_prompt="system",
        prompt="prove this",
        transcript=[RuntimeMessage(role="user", content="hello")],
        cwd=tmp_path,
    )
    schema = tmp_path / "schema.json"
    schema.write_text('{"type":"object"}', encoding="utf-8")

    fresh, fresh_stdin = backend.build_fresh_command(invocation, schema)
    resumed, resumed_stdin = backend.build_resume_command(invocation, "session-xyz", schema)
    assert fresh[:4] == ["codex", "--ask-for-approval", "on-request", "exec"]
    assert "--output-schema" in fresh
    assert resumed[:5] == ["codex", "--ask-for-approval", "on-request", "exec", "resume"]
    assert fresh_stdin is not None and invocation.prompt in fresh_stdin
    assert resumed[-1] == "-"
    assert resumed_stdin == invocation.prompt


class FakeBackend(RuntimeBackend):
    name = "fake"

    def build_fresh_command(self, invocation: RuntimeInvocation, schema_path: Path | None):
        return ["fake"], invocation.prompt

    def build_resume_command(self, invocation: RuntimeInvocation, session_id: str, schema_path: Path | None):
        return ["fake", session_id], invocation.prompt


class FakeAPIRuntime(RuntimeBackend):
    name = "fake-api"
    supports_native_resume = False

    def is_api_backend(self) -> bool:
        return True

    async def invoke_api(self, invocation: RuntimeInvocation):
        return (
            json.dumps({"ok": True}),
            {
                "provider_usage": {"input_tokens": 12, "output_tokens": 3},
                "provider_model": self.config.model,
            },
        )


@pytest.mark.parametrize(
    ("backend_name", "api_key"),
    [
        ("codex", ""),
        ("claude", ""),
        ("openai", "test-key"),
        ("anthropic", "test-key"),
        ("deepseek", "test-key"),
        ("gemini", "test-key"),
    ],
)
def test_build_backend_supports_all_declared_backends(backend_name: str, api_key: str):
    runtime = load_config().runtime.__class__(
        backend=backend_name,
        model="test-model",
        effort="low",
        profile="",
        sandbox="workspace-write",
        approval_policy="on-request",
        persist_session=False,
        workspace_mode="shared",
        cli_path=default_cli_path(backend_name),
        api_key=api_key,
    )

    backend = build_backend(runtime)
    assert backend.name == backend_name


def test_agent_runtime_session_records_prompt_metadata(tmp_path: Path, monkeypatch):
    async def fake_run(command, cwd, stdin_input=None):
        return ("ok", "")

    monkeypatch.setattr(AgentRuntimeSession, "_run_command", staticmethod(fake_run))

    session = AgentRuntimeSession(
        role="thinking",
        runtime_config=load_config().runtime,
        backend=FakeBackend(load_config().runtime),
        root_dir=tmp_path / "runtime",
        workspace=tmp_path,
    )
    result = asyncio.run(
        session.invoke(
            system_prompt="system",
            transcript=[RuntimeMessage(role="user", content="prior")],
            prompt="current prompt",
            use_native_session=False,
            metadata={
                "callsite": "thinking.generate_roadmaps",
                "document_char_counts": {"memo": 321},
                "transcript_char_counts": {"history": 5},
                "near_limit_chars": 10,
            },
        )
    )

    result_path = Path(result.metadata["invocation_dir"]) / "result.json"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    meta = payload["metadata"]
    assert meta["callsite"] == "thinking.generate_roadmaps"
    assert meta["document_char_counts"] == {"memo": 321}
    assert meta["transcript_char_counts"] == {"history": 5}
    assert meta["prompt_chars"] > 0
    assert meta["transcript_chars"] == len("prior")
    assert meta["near_limit"] is True


def test_agent_runtime_session_api_backend_records_provider_metadata(tmp_path: Path):
    runtime = load_config().runtime.__class__(
        backend="openai",
        model="o3",
        effort="low",
        profile="",
        sandbox="workspace-write",
        approval_policy="on-request",
        persist_session=True,
        workspace_mode="shared",
        cli_path="",
        api_key="test-key",
        max_retries=0,
        retry_backoff_ms=0,
    )

    session = AgentRuntimeSession(
        role="thinking",
        runtime_config=runtime,
        backend=FakeAPIRuntime(runtime),
        root_dir=tmp_path / "runtime",
        workspace=tmp_path,
    )
    result = asyncio.run(
        session.invoke(
            system_prompt="system",
            transcript=[RuntimeMessage(role="user", content="prior")],
            prompt="current prompt",
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
            metadata={"callsite": "thinking.generate_roadmaps"},
        )
    )

    assert result.backend == "openai"
    assert result.structured_output == {"ok": True}
    assert result.used_native_resume is False
    assert result.session_id == ""
    assert result.metadata["provider_usage"] == {"input_tokens": 12, "output_tokens": 3}
    assert result.metadata["provider_model"] == "o3"
    assert result.metadata["retry_count"] == 0
    state = session.state
    assert state.supports_native_resume is False
    assert state.session_id == ""


def test_agent_runtime_session_retries_transient_failures(tmp_path: Path, monkeypatch):
    calls = {"count": 0}

    async def flaky_run(command, cwd, stdin_input=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise CommandExecutionError(1, command, "", "429 rate limit")
        return ("ok after retry", "")

    monkeypatch.setattr(AgentRuntimeSession, "_run_command", staticmethod(flaky_run))

    runtime = load_config().runtime.__class__(
        backend=load_config().runtime.backend,
        model=load_config().runtime.model,
        effort=load_config().runtime.effort,
        profile=load_config().runtime.profile,
        sandbox=load_config().runtime.sandbox,
        approval_policy=load_config().runtime.approval_policy,
        persist_session=False,
        workspace_mode=load_config().runtime.workspace_mode,
        cli_path=load_config().runtime.cli_path,
        max_retries=1,
        retry_backoff_ms=0,
    )

    session = AgentRuntimeSession(
        role="thinking",
        runtime_config=runtime,
        backend=FakeBackend(runtime),
        root_dir=tmp_path / "runtime",
        workspace=tmp_path,
    )
    result = asyncio.run(
        session.invoke(
            system_prompt="system",
            transcript=[],
            prompt="current prompt",
            use_native_session=False,
            metadata={"callsite": "thinking.generate_roadmaps"},
        )
    )

    assert result.content == "ok after retry"
    assert result.metadata["retry_count"] == 1
    assert result.metadata["retry_reasons"] == ["rate_limit"]
