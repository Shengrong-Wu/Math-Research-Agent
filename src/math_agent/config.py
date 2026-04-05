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


@dataclass(frozen=True)
class Hyperparameters:
    """Tunable search parameters."""

    N: int = 5  # steps per roadmap
    C: int = 8  # context compression interval
    K: int = 3  # diminishing-returns window


@dataclass(frozen=True)
class ProviderConfig:
    """LLM provider settings."""

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
    lean: LeanConfig = field(default_factory=LeanConfig)
    problem_id: str = ""
    suite: str = ""
    runs_dir: Path = Path("runs")


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
        lean=LeanConfig(
            toolchain=lean_raw.get("toolchain", "leanprover/lean4:v4.14.0"),
            mathlib=lean_raw.get("mathlib", True),
        ),
        problem_id=raw.get("problem_id", ""),
        suite=raw.get("suite", ""),
        runs_dir=Path(raw.get("runs_dir", "runs")),
    )
