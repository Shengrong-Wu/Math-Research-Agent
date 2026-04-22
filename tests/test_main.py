from __future__ import annotations

import sys

from math_agent import main as main_module


def test_provider_alias_updates_backend_and_model(monkeypatch, caplog):
    captured = {}

    async def fake_run_agent(config, problem, resume_from=None):
        captured["config"] = config
        captured["problem"] = problem
        captured["resume_from"] = resume_from

    monkeypatch.setattr(main_module, "run_agent", fake_run_agent)
    monkeypatch.setattr(
        sys,
        "argv",
        ["math-agent", "--question", "Prove x = x.", "--provider", "openai"],
    )

    with caplog.at_level("WARNING"):
        main_module.main()

    assert "--provider is deprecated" in caplog.text
    assert captured["config"].runtime.backend == "openai"
    assert captured["config"].runtime.model == "o3"
    assert captured["problem"].question == "Prove x = x."
