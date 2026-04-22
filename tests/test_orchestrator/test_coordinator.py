from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from math_agent.config import AppConfig, LeanConfig
from math_agent.orchestrator.coordinator import Coordinator
from math_agent.orchestrator.phase1 import Phase1Result
from math_agent.problem.spec import ProblemSpec


def _problem() -> ProblemSpec:
    return ProblemSpec(
        problem_id="custom",
        question="Prove something simple.",
        domain="general",
        difficulty_level=1,
        difficulty_label="toy",
    )


def test_prepare_toolplane_reuses_bootstrapped_workspace(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "lean-workspace"
    workspace.mkdir(parents=True)
    (workspace / "lean-toolchain").write_text("leanprover/lean4:v4.14.0\n", encoding="utf-8")
    (workspace / "lakefile.toml").write_text('name = "mathAgent"\n', encoding="utf-8")
    (workspace / ".lake" / "packages" / "mathlib").mkdir(parents=True)
    (workspace / ".math-agent-bootstrap.json").write_text(
        json.dumps({"toolchain": "leanprover/lean4:v4.14.0", "mathlib": True}),
        encoding="utf-8",
    )

    config = AppConfig(
        lean_mode="check",
        lean=LeanConfig(
            toolchain="leanprover/lean4:v4.14.0",
            mathlib=True,
            workspace=workspace,
        ),
    )
    coordinator = Coordinator(config=config, problem=_problem())

    calls = {"project_init": 0, "cache_get": 0, "subprocess": 0}

    class FakeProject:
        def __init__(self, workspace: Path, toolchain: str, use_mathlib: bool = True) -> None:
            self.workspace = workspace

        def init(self) -> None:
            calls["project_init"] += 1

    class FakeCompiler:
        def __init__(self, workspace: Path) -> None:
            self.workspace = workspace

        async def cache_get(self) -> bool:
            calls["cache_get"] += 1
            return True

    class FakeToolplane:
        @staticmethod
        def is_available() -> bool:
            return True

        def __init__(self, compiler, workspace: Path) -> None:
            self.compiler = compiler
            self.workspace = workspace

    def fake_run(*args, **kwargs):
        calls["subprocess"] += 1
        raise AssertionError("bootstrap should not run when the shared workspace stamp matches")

    monkeypatch.setattr("math_agent.lean.project.LeanProject", FakeProject)
    monkeypatch.setattr("math_agent.lean.compiler.LeanCompiler", FakeCompiler)
    monkeypatch.setattr("math_agent.lean.toolplane.LeanToolplane", FakeToolplane)
    monkeypatch.setattr("math_agent.orchestrator.coordinator.subprocess.run", fake_run)

    toolplane = asyncio.run(coordinator._prepare_toolplane())

    assert isinstance(toolplane, FakeToolplane)
    assert toolplane.workspace == workspace
    assert calls == {"project_init": 1, "cache_get": 0, "subprocess": 0}
    stamp = json.loads((workspace / ".math-agent-bootstrap.json").read_text(encoding="utf-8"))
    assert stamp == {"toolchain": "leanprover/lean4:v4.14.0", "mathlib": True}


def test_prepare_toolplane_reuses_compatible_workspace_without_stamp(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "lean-workspace"
    workspace.mkdir(parents=True)
    (workspace / "lean-toolchain").write_text("leanprover/lean4:v4.14.0\n", encoding="utf-8")
    (workspace / "lakefile.toml").write_text('name = "mathAgent"\n', encoding="utf-8")
    (workspace / ".lake" / "packages" / "mathlib").mkdir(parents=True)

    config = AppConfig(
        lean_mode="check",
        lean=LeanConfig(
            toolchain="leanprover/lean4:v4.14.0",
            mathlib=True,
            workspace=workspace,
        ),
    )
    coordinator = Coordinator(config=config, problem=_problem())

    calls = {"project_init": 0, "cache_get": 0, "subprocess": 0}

    class FakeProject:
        def __init__(self, workspace: Path, toolchain: str, use_mathlib: bool = True) -> None:
            self.workspace = workspace

        def init(self) -> None:
            calls["project_init"] += 1

    class FakeCompiler:
        def __init__(self, workspace: Path) -> None:
            self.workspace = workspace

        async def cache_get(self) -> bool:
            calls["cache_get"] += 1
            return True

    class FakeToolplane:
        @staticmethod
        def is_available() -> bool:
            return True

        def __init__(self, compiler, workspace: Path) -> None:
            self.compiler = compiler
            self.workspace = workspace

    def fake_run(*args, **kwargs):
        calls["subprocess"] += 1
        raise AssertionError("bootstrap should not run when the shared workspace is already compatible")

    monkeypatch.setattr("math_agent.lean.project.LeanProject", FakeProject)
    monkeypatch.setattr("math_agent.lean.compiler.LeanCompiler", FakeCompiler)
    monkeypatch.setattr("math_agent.lean.toolplane.LeanToolplane", FakeToolplane)
    monkeypatch.setattr("math_agent.orchestrator.coordinator.subprocess.run", fake_run)

    toolplane = asyncio.run(coordinator._prepare_toolplane())

    assert isinstance(toolplane, FakeToolplane)
    assert toolplane.workspace == workspace
    assert calls == {"project_init": 1, "cache_get": 0, "subprocess": 0}
    stamp = json.loads((workspace / ".math-agent-bootstrap.json").read_text(encoding="utf-8"))
    assert stamp == {"toolchain": "leanprover/lean4:v4.14.0", "mathlib": True}


def test_prepare_toolplane_bootstraps_once_and_writes_stamp(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "lean-workspace"
    config = AppConfig(
        lean_mode="check",
        lean=LeanConfig(
            toolchain="leanprover/lean4:v4.14.0",
            mathlib=True,
            workspace=workspace,
        ),
    )
    coordinator = Coordinator(config=config, problem=_problem())

    calls = {"project_init": 0, "cache_get": 0, "subprocess": 0}

    class FakeProject:
        def __init__(self, workspace: Path, toolchain: str, use_mathlib: bool = True) -> None:
            self.workspace = workspace
            self.toolchain = toolchain

        def init(self) -> None:
            calls["project_init"] += 1
            self.workspace.mkdir(parents=True, exist_ok=True)
            (self.workspace / "lean-toolchain").write_text(self.toolchain + "\n", encoding="utf-8")
            (self.workspace / "lakefile.toml").write_text('name = "mathAgent"\n', encoding="utf-8")

    class FakeCompiler:
        def __init__(self, workspace: Path) -> None:
            self.workspace = workspace
            self._lake = "lake"
            self._env = {}

        async def cache_get(self) -> bool:
            calls["cache_get"] += 1
            (self.workspace / ".lake" / "packages" / "mathlib").mkdir(parents=True, exist_ok=True)
            return True

    class FakeToolplane:
        @staticmethod
        def is_available() -> bool:
            return True

        def __init__(self, compiler, workspace: Path) -> None:
            self.compiler = compiler
            self.workspace = workspace

    def fake_run(*args, **kwargs):
        calls["subprocess"] += 1
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("math_agent.lean.project.LeanProject", FakeProject)
    monkeypatch.setattr("math_agent.lean.compiler.LeanCompiler", FakeCompiler)
    monkeypatch.setattr("math_agent.lean.toolplane.LeanToolplane", FakeToolplane)
    monkeypatch.setattr("math_agent.orchestrator.coordinator.subprocess.run", fake_run)

    toolplane = asyncio.run(coordinator._prepare_toolplane())

    assert isinstance(toolplane, FakeToolplane)
    assert calls == {"project_init": 1, "cache_get": 1, "subprocess": 1}
    stamp = json.loads((workspace / ".math-agent-bootstrap.json").read_text(encoding="utf-8"))
    assert stamp == {"toolchain": "leanprover/lean4:v4.14.0", "mathlib": True}


def test_run_keeps_lean_workspace_outside_run_artifacts(tmp_path: Path, monkeypatch):
    config = AppConfig(
        lean_mode="check",
        runs_dir=tmp_path / "runs",
    )
    coordinator = Coordinator(config=config, problem=_problem())

    async def fake_prepare_toolplane():
        return object()

    async def fake_phase1_run(self):
        return Phase1Result(success=True, roadmaps_attempted=1)

    monkeypatch.setattr(coordinator, "_prepare_toolplane", fake_prepare_toolplane)
    monkeypatch.setattr("math_agent.orchestrator.coordinator.Phase1Runner.run", fake_phase1_run)

    result = asyncio.run(coordinator.run())

    assert result.success is True
    assert result.run_dir is not None
    assert not (result.run_dir / "lean-workspace").exists()
    summary = json.loads((result.run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["lean_mode"] == "check"
    assert (result.run_dir / "agent_runtime").is_dir()
