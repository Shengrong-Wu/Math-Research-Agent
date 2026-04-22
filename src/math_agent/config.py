"""Configuration loading and compatibility helpers for Math Agent."""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 12):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - py311 fallback
        import tomli as tomllib  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

CLI_BACKENDS = frozenset({"codex", "claude"})
API_BACKENDS = frozenset({"openai", "anthropic", "deepseek", "gemini"})
VALID_BACKENDS = CLI_BACKENDS | API_BACKENDS
VALID_WORKSPACE_MODES = frozenset({"shared", "per_run", "per_task"})
VALID_LEAN_MODES = frozenset({"off", "check"})

DEFAULT_MODELS: dict[str, str] = {
    "codex": "gpt-5.4",
    "claude": "sonnet",
    "openai": "o3",
    "anthropic": "claude-opus-4-1",
    "deepseek": "deepseek-reasoner",
    "gemini": "gemini-2.5-pro",
}

KNOWN_MODELS: dict[str, list[str]] = {
    "codex": ["gpt-5.4", "gpt-5.4-mini", "o3"],
    "claude": ["opus", "sonnet"],
    "openai": ["o3", "gpt-5.4", "gpt-5.4-mini"],
    "anthropic": ["claude-opus-4-1", "claude-sonnet-4-5"],
    "deepseek": ["deepseek-reasoner", "deepseek-chat"],
    "gemini": ["gemini-2.5-pro", "gemini-2.5-flash"],
}

DEFAULT_CLI_PATHS: dict[str, str] = {
    "claude": shutil.which("claude") or "/Users/wsr_sg/.local/bin/claude",
    "codex": shutil.which("codex") or "/opt/homebrew/bin/codex",
}

API_KEY_ENVS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


@dataclass(frozen=True)
class Hyperparameters:
    """Tunable search parameters for the Thinking Agent."""

    n_min: int = 5
    n_max: int = 15
    C: int = 8
    K: int = 3

    @property
    def N(self) -> int:  # noqa: N802
        return self.n_max


@dataclass(frozen=True)
class PromptBudgetConfig:
    """Hard character budgets for prompt assembly by call site."""

    roadmap_generation: int = 60_000
    step_work: int = 12_000
    proof_compilation: int = 140_000
    review: int = 24_000
    falsifier: int = 40_000
    near_limit_chars: int = 750_000


@dataclass(frozen=True)
class LeanConfig:
    """Lean 4 settings for optional verification."""

    toolchain: str = "leanprover/lean4:v4.14.0"
    mathlib: bool = True
    workspace: Path = field(
        default_factory=lambda: _PROJECT_ROOT / ".cache" / "lean-workspace"
    )


@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved execution backend settings for one agent."""

    backend: str = "codex"
    model: str = ""
    effort: str = "low"
    temperature: float = 0.7
    profile: str = ""
    sandbox: str = "workspace-write"
    approval_policy: str = "on-request"
    persist_session: bool = True
    workspace_mode: str = "shared"
    cli_path: str = ""
    api_key: str = ""
    max_retries: int = 2
    retry_backoff_ms: int = 500


@dataclass(frozen=True)
class AgentRuntimeConfig:
    """Per-agent runtime overrides."""

    backend: str = ""
    model: str = ""
    effort: str = ""
    temperature: float | None = None
    profile: str = ""
    sandbox: str = ""
    approval_policy: str = ""
    persist_session: bool | None = None
    workspace_mode: str = ""
    cli_path: str = ""
    api_key: str = ""
    max_retries: int | None = None
    retry_backoff_ms: int | None = None


@dataclass(frozen=True)
class AgentConfigs:
    thinking: AgentRuntimeConfig = field(default_factory=AgentRuntimeConfig)
    formalizer: AgentRuntimeConfig = field(default_factory=AgentRuntimeConfig)
    assistant: AgentRuntimeConfig = field(default_factory=AgentRuntimeConfig)
    review: AgentRuntimeConfig = field(default_factory=AgentRuntimeConfig)
    falsifier: AgentRuntimeConfig = field(default_factory=AgentRuntimeConfig)


@dataclass(frozen=True)
class AppConfig:
    hyper: Hyperparameters = field(default_factory=Hyperparameters)
    prompt_budgets: PromptBudgetConfig = field(default_factory=PromptBudgetConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    agents: AgentConfigs = field(default_factory=AgentConfigs)
    lean: LeanConfig = field(default_factory=LeanConfig)
    lean_mode: str = "off"
    problem_id: str = ""
    suite: str = ""
    runs_dir: Path = field(default_factory=lambda: _PROJECT_ROOT / "runs")


def _normalize_backend(name: str) -> str:
    raw = (name or "").strip().lower()
    if raw in VALID_BACKENDS:
        return raw
    return "codex"


def default_cli_path(backend: str) -> str:
    backend = _normalize_backend(backend)
    return DEFAULT_CLI_PATHS.get(backend, "")


def _normalize_cli_path(backend: str, cli_path: str) -> str:
    backend = _normalize_backend(backend)
    if backend not in CLI_BACKENDS:
        return ""
    return cli_path or default_cli_path(backend)


def _normalize_workspace_mode(mode: str) -> str:
    if mode in VALID_WORKSPACE_MODES:
        return mode
    return "shared"


def _resolve_path(value: object, default: Path) -> Path:
    if value in (None, ""):
        return default
    path = Path(str(value))
    return path if path.is_absolute() else (_PROJECT_ROOT / path)


def _resolve_api_key(backend: str, api_key: str) -> str:
    if api_key:
        return api_key
    env_name = API_KEY_ENVS.get(_normalize_backend(backend), "")
    return os.environ.get(env_name, "") if env_name else ""


def _normalize_temperature(value: object, fallback: float = 0.7) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _normalize_lean_mode(raw_mode: object, *, source: str) -> str:
    mode = str(raw_mode or "").strip().lower()
    if not mode:
        return "off"
    if mode == "full":
        logger.warning("%s requested lean_mode=full; normalizing to check.", source)
        return "check"
    if mode in VALID_LEAN_MODES:
        return mode
    logger.warning("%s requested unknown lean_mode=%r; falling back to off.", source, raw_mode)
    return "off"


def _normalize_runtime(raw: dict) -> RuntimeConfig:
    backend = _normalize_backend(raw.get("backend", raw.get("name", "codex")))
    return RuntimeConfig(
        backend=backend,
        model=raw.get("model", "") or DEFAULT_MODELS.get(backend, ""),
        effort=str(raw.get("effort", "low") or "low"),
        temperature=_normalize_temperature(raw.get("temperature", 0.7)),
        profile=str(raw.get("profile", "")),
        sandbox=str(raw.get("sandbox", "workspace-write") or "workspace-write"),
        approval_policy=str(raw.get("approval_policy", "on-request") or "on-request"),
        persist_session=bool(raw.get("persist_session", True)),
        workspace_mode=_normalize_workspace_mode(
            str(raw.get("workspace_mode", "shared") or "shared")
        ),
        cli_path=_normalize_cli_path(backend, str(raw.get("cli_path", ""))),
        api_key=_resolve_api_key(backend, str(raw.get("api_key", ""))),
        max_retries=max(0, int(raw.get("max_retries", 2))),
        retry_backoff_ms=max(0, int(raw.get("retry_backoff_ms", 500))),
    )


def _load_agent_runtime(raw: dict) -> AgentRuntimeConfig:
    backend = _normalize_backend(raw.get("backend", raw.get("name", ""))) if raw else ""
    persist_session = raw.get("persist_session", None)
    if persist_session is not None:
        persist_session = bool(persist_session)
    return AgentRuntimeConfig(
        backend=backend if raw else "",
        model=raw.get("model", "") if raw else "",
        effort=str(raw.get("effort", "")) if raw else "",
        temperature=(
            _normalize_temperature(raw.get("temperature", 0.7))
            if raw and raw.get("temperature") is not None
            else None
        ),
        profile=str(raw.get("profile", "")) if raw else "",
        sandbox=str(raw.get("sandbox", "")) if raw else "",
        approval_policy=str(raw.get("approval_policy", "")) if raw else "",
        persist_session=persist_session,
        workspace_mode=str(raw.get("workspace_mode", "")) if raw else "",
        cli_path=str(raw.get("cli_path", "")) if raw else "",
        api_key=str(raw.get("api_key", "")) if raw else "",
        max_retries=(
            max(0, int(raw.get("max_retries", 0)))
            if raw and raw.get("max_retries") is not None
            else None
        ),
        retry_backoff_ms=(
            max(0, int(raw.get("retry_backoff_ms", 0)))
            if raw and raw.get("retry_backoff_ms") is not None
            else None
        ),
    )


def resolve_agent_runtime(
    agent_cfg: AgentRuntimeConfig,
    shared: RuntimeConfig,
) -> RuntimeConfig:
    """Return the resolved runtime config for a specific agent role."""

    backend = agent_cfg.backend or shared.backend
    model = agent_cfg.model or shared.model or DEFAULT_MODELS.get(backend, "")
    effort = agent_cfg.effort or shared.effort
    profile = agent_cfg.profile or shared.profile
    sandbox = agent_cfg.sandbox or shared.sandbox
    approval_policy = agent_cfg.approval_policy or shared.approval_policy
    temperature = (
        agent_cfg.temperature
        if agent_cfg.temperature is not None
        else shared.temperature
    )
    persist_session = (
        agent_cfg.persist_session
        if agent_cfg.persist_session is not None
        else shared.persist_session
    )
    max_retries = (
        agent_cfg.max_retries
        if agent_cfg.max_retries is not None
        else shared.max_retries
    )
    retry_backoff_ms = (
        agent_cfg.retry_backoff_ms
        if agent_cfg.retry_backoff_ms is not None
        else shared.retry_backoff_ms
    )
    workspace_mode = _normalize_workspace_mode(
        agent_cfg.workspace_mode or shared.workspace_mode
    )
    if agent_cfg.cli_path:
        cli_path = _normalize_cli_path(backend, agent_cfg.cli_path)
    elif backend == shared.backend:
        cli_path = _normalize_cli_path(backend, shared.cli_path)
    else:
        cli_path = default_cli_path(backend)
    api_key = _resolve_api_key(backend, agent_cfg.api_key or shared.api_key)
    return RuntimeConfig(
        backend=backend,
        model=model,
        effort=effort,
        temperature=temperature,
        profile=profile,
        sandbox=sandbox,
        approval_policy=approval_policy,
        persist_session=persist_session,
        workspace_mode=workspace_mode,
        cli_path=cli_path,
        api_key=api_key,
        max_retries=max_retries,
        retry_backoff_ms=retry_backoff_ms,
    )


def load_config(path: Path | None = None) -> AppConfig:
    """Load configuration from TOML with compatibility for old provider configs."""

    if path is None:
        path = _PROJECT_ROOT / "configs" / "default.toml"
    if not path.exists():
        return AppConfig()

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    hyper_raw = raw.get("hyperparameters", {})
    runtime_raw = raw.get("runtime", raw.get("provider", {}))
    agents_raw = raw.get("agents", {})
    budgets_raw = raw.get("prompt_budgets", {})
    lean_raw = raw.get("lean", {})

    old_n = hyper_raw.get("N", None)
    if "n_min" in hyper_raw or "n_max" in hyper_raw:
        n_min = hyper_raw.get("n_min", 5)
        n_max = hyper_raw.get("n_max", 15)
    elif old_n is not None:
        n_min = max(3, old_n - 2)
        n_max = old_n + 5
    else:
        n_min, n_max = 5, 15

    if "cli" in agents_raw and agents_raw.get("cli"):
        logger.warning("Ignoring legacy [agents.cli] runtime config; full Lean formalization is no longer supported.")

    lean_mode_raw = hyper_raw.get("lean_mode", raw.get("lean_mode", None))
    if lean_mode_raw is not None:
        lean_mode = _normalize_lean_mode(lean_mode_raw, source=str(path))
    else:
        old_skip = hyper_raw.get("skip_lean", raw.get("skip_lean", False))
        lean_mode = "off" if old_skip else "check"

    agents = AgentConfigs(
        thinking=_load_agent_runtime(agents_raw.get("thinking", {})),
        formalizer=_load_agent_runtime(agents_raw.get("formalizer", {})),
        assistant=_load_agent_runtime(agents_raw.get("assistant", {})),
        review=_load_agent_runtime(agents_raw.get("review", {})),
        falsifier=_load_agent_runtime(agents_raw.get("falsifier", {})),
    )

    lean_toolchain = str(lean_raw.get("toolchain", "leanprover/lean4:v4.14.0"))
    lean_mathlib = bool(lean_raw.get("mathlib", True))
    lean_workspace = _resolve_path(
        lean_raw.get("workspace", None),
        _PROJECT_ROOT / ".cache" / "lean-workspace",
    )

    return AppConfig(
        hyper=Hyperparameters(
            n_min=int(n_min),
            n_max=int(max(n_min, n_max)),
            C=int(hyper_raw.get("C", 8)),
            K=int(hyper_raw.get("K", 3)),
        ),
        prompt_budgets=PromptBudgetConfig(
            roadmap_generation=int(budgets_raw.get("roadmap_generation", 60_000)),
            step_work=int(budgets_raw.get("step_work", 12_000)),
            proof_compilation=int(budgets_raw.get("proof_compilation", 140_000)),
            review=int(budgets_raw.get("review", 24_000)),
            falsifier=int(budgets_raw.get("falsifier", 40_000)),
            near_limit_chars=int(budgets_raw.get("near_limit_chars", 750_000)),
        ),
        runtime=_normalize_runtime(runtime_raw),
        agents=agents,
        lean=LeanConfig(
            toolchain=lean_toolchain,
            mathlib=lean_mathlib,
            workspace=lean_workspace,
        ),
        lean_mode=lean_mode,
        problem_id=str(raw.get("problem_id", "")),
        suite=str(raw.get("suite", "")),
        runs_dir=_resolve_path(raw.get("runs_dir", None), _PROJECT_ROOT / "runs"),
    )
