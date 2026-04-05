"""Configuration loading and validation."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 12):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Default model tables
# ---------------------------------------------------------------------------

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-opus-4-0626",
    "openai": "o3",
    "deepseek": "deepseek-reasoner",
    "gemini": "gemini-2.5-pro",
}

API_KEY_ENVS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Hyperparameters:
    """Tunable search parameters."""

    N: int = 5  # steps per roadmap
    C: int = 8  # context compression interval
    K: int = 3  # diminishing-returns window


@dataclass(frozen=True)
class AgentProvider:
    """Provider + model configuration for a single agent.

    When *name* is empty the agent inherits the shared default provider.
    When *model* is empty the agent uses the provider's default model.
    """

    name: str = ""       # provider name (anthropic / openai / deepseek / gemini)
    model: str = ""      # model override
    temperature: float = 0.7
    api_key: str = ""    # resolved from env at runtime


@dataclass(frozen=True)
class AgentConfigs:
    """Per-agent provider/model overrides.

    Any field left at its default (empty *name*) inherits the shared
    ``[provider]`` table so the user can configure one provider for all
    agents or mix-and-match freely.

    Example TOML for mixed providers::

        [agents.thinking]
        name = "openai"
        model = "gpt-5.4-xhigh"

        [agents.assistant]
        name = "gemini"
        model = "gemini-3-flash"

        [agents.review]
        name = "anthropic"
        model = "claude-sonnet-4.6"

        [agents.cli]
        name = "anthropic"
        model = "claude-sonnet-4.6"
    """

    thinking: AgentProvider = field(default_factory=AgentProvider)
    assistant: AgentProvider = field(default_factory=AgentProvider)
    review: AgentProvider = field(default_factory=AgentProvider)
    cli: AgentProvider = field(default_factory=AgentProvider)


@dataclass(frozen=True)
class ProviderConfig:
    """Shared (default) LLM provider settings.

    Used by any agent whose ``AgentProvider.name`` is empty.
    """

    name: str = "anthropic"
    model: str = ""
    temperature: float = 0.7
    api_key: str = ""  # resolved from env at runtime


@dataclass(frozen=True)
class LeanConfig:
    """Lean 4 toolchain settings."""

    toolchain: str = "leanprover/lean4:v4.14.0"
    mathlib: bool = True


@dataclass(frozen=True)
class AppConfig:
    """Top-level application configuration."""

    hyper: Hyperparameters = field(default_factory=Hyperparameters)
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    agents: AgentConfigs = field(default_factory=AgentConfigs)
    lean: LeanConfig = field(default_factory=LeanConfig)
    skip_lean: bool = False  # stop after Phase 1 (no Lean formalization)
    problem_id: str = ""
    suite: str = ""
    runs_dir: Path = Path("runs")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolve_agent_provider(
    agent_cfg: AgentProvider,
    shared: ProviderConfig,
) -> tuple[str, str, float]:
    """Return (provider_name, model, temperature) for an agent.

    Falls back to the shared provider when the agent-level config is empty.
    """
    name = agent_cfg.name or shared.name
    model = agent_cfg.model or shared.model or DEFAULT_MODELS.get(name, "")
    temp = agent_cfg.temperature if agent_cfg.name else shared.temperature
    return name, model, temp


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _load_agent_provider(raw: dict) -> AgentProvider:
    return AgentProvider(
        name=raw.get("name", ""),
        model=raw.get("model", ""),
        temperature=raw.get("temperature", 0.7),
    )


def load_config(path: Path | None = None) -> AppConfig:
    """Load configuration from a TOML file, falling back to defaults."""
    if path is None:
        path = Path("configs/default.toml")
    if not path.exists():
        return AppConfig()

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    hyper_raw = raw.get("hyperparameters", {})
    provider_raw = raw.get("provider", {})
    lean_raw = raw.get("lean", {})
    agents_raw = raw.get("agents", {})

    agents = AgentConfigs(
        thinking=_load_agent_provider(agents_raw.get("thinking", {})),
        assistant=_load_agent_provider(agents_raw.get("assistant", {})),
        review=_load_agent_provider(agents_raw.get("review", {})),
        cli=_load_agent_provider(agents_raw.get("cli", {})),
    )

    return AppConfig(
        hyper=Hyperparameters(
            N=hyper_raw.get("N", 5),
            C=hyper_raw.get("C", 8),
            K=hyper_raw.get("K", 3),
        ),
        provider=ProviderConfig(
            name=provider_raw.get("name", "anthropic"),
            model=provider_raw.get("model", ""),
            temperature=provider_raw.get("temperature", 0.7),
        ),
        agents=agents,
        lean=LeanConfig(
            toolchain=lean_raw.get("toolchain", "leanprover/lean4:v4.14.0"),
            mathlib=lean_raw.get("mathlib", True),
        ),
        skip_lean=raw.get("skip_lean", False),
        problem_id=raw.get("problem_id", ""),
        suite=raw.get("suite", ""),
        runs_dir=Path(raw.get("runs_dir", "runs")),
    )
