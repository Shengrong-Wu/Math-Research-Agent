"""Factory helpers for runtime sessions."""

from __future__ import annotations

from pathlib import Path

from math_agent.config import AppConfig, CLI_BACKENDS, RuntimeConfig, resolve_agent_runtime
from math_agent.runtime.api import (
    AnthropicRuntime,
    DeepSeekRuntime,
    GeminiRuntime,
    OpenAIRuntime,
)
from math_agent.runtime.base import AgentRuntimeSession, RuntimeBackend
from math_agent.runtime.claude import ClaudeRuntime
from math_agent.runtime.codex import CodexRuntime


def build_backend(config: RuntimeConfig) -> RuntimeBackend:
    if config.backend == "claude":
        return ClaudeRuntime(config)
    if config.backend == "codex":
        return CodexRuntime(config)
    if config.backend == "anthropic":
        return AnthropicRuntime(config)
    if config.backend == "openai":
        return OpenAIRuntime(config)
    if config.backend == "deepseek":
        return DeepSeekRuntime(config)
    if config.backend == "gemini":
        return GeminiRuntime(config)
    raise ValueError(f"Unsupported runtime backend: {config.backend}")


def build_role_sessions(
    config: AppConfig,
    runtime_root: Path,
    *,
    default_workspace: Path,
    cli_workspace: Path | None = None,
) -> dict[str, AgentRuntimeSession]:
    """Build one runtime session per agent role."""

    shared = config.runtime
    cli_workspace = cli_workspace or default_workspace
    sessions: dict[str, AgentRuntimeSession] = {}

    for role in ("thinking", "formalizer", "assistant", "review", "falsifier"):
        resolved = resolve_agent_runtime(getattr(config.agents, role), shared)
        workspace = cli_workspace if resolved.backend in CLI_BACKENDS else default_workspace
        sessions[role] = AgentRuntimeSession(
            role=role,
            runtime_config=resolved,
            backend=build_backend(resolved),
            root_dir=runtime_root / role,
            workspace=workspace,
        )

    return sessions
