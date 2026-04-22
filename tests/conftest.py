from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from math_agent.config import RuntimeConfig
from math_agent.runtime import RuntimeResult


class MockRuntimeSession:
    """Mock runtime session for tests."""

    def __init__(self, responses: list[str] | None = None, *, role: str = "test"):
        self._responses = list(responses or ["Mock response."])
        self._call_count = 0
        self.calls: list[dict] = []
        self.role = role
        self.root_dir = Path("/tmp") / "math_agent_test_runtime" / role
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.workspace = self.root_dir
        self.runtime_config = RuntimeConfig(backend="claude", model="mock-model")

    async def invoke(
        self,
        *,
        system_prompt: str,
        transcript,
        prompt: str,
        output_schema=None,
        use_native_session=None,
        cwd=None,
        metadata=None,
    ) -> RuntimeResult:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "transcript": transcript,
                "prompt": prompt,
                "output_schema": output_schema,
                "use_native_session": use_native_session,
                "cwd": cwd,
                "metadata": metadata,
            }
        )
        idx = min(self._call_count, len(self._responses) - 1)
        response = self._responses[idx]
        self._call_count += 1
        structured = None
        if output_schema is not None:
            structured = json.loads(response)
        return RuntimeResult(
            content=response,
            model="mock-model",
            backend="claude",
            structured_output=structured,
        )

    def export_context(self, name: str, messages) -> Path:
        target = self.root_dir / f"{name}.json"
        target.write_text("[]", encoding="utf-8")
        return target

    def fork(self, *, role: str, root_dir: Path, workspace: Path | None = None, seed_messages=None, runtime_config=None, backend=None):
        forked = MockRuntimeSession(self._responses[self._call_count :], role=role)
        forked.root_dir = root_dir
        forked.root_dir.mkdir(parents=True, exist_ok=True)
        forked.workspace = workspace or self.workspace
        forked.runtime_config = runtime_config or self.runtime_config
        return forked


@pytest.fixture
def tmp_run_dir(tmp_path: Path) -> Path:
    d = tmp_path / "test_run"
    d.mkdir()
    return d


@pytest.fixture
def mock_runtime() -> MockRuntimeSession:
    return MockRuntimeSession()
