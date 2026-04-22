from __future__ import annotations

import asyncio

from math_agent.agents.formalizer import FormalizerAgent


async def _formalize_statement(agent: FormalizerAgent) -> str:
    return await agent.formalize_statement(
        "Prove that x = x.",
        "Use reflexivity.",
    )


async def _formalize_step_sketch(agent: FormalizerAgent) -> str:
    return await agent.formalize_step_sketch(
        "Prove that x = x.",
        "Show the claim follows by reflexivity.",
        ["x = x"],
    )


def test_formalizer_extracts_fenced_statement(mock_runtime):
    mock_runtime._responses = [
        "```lean\nimport Mathlib.Tactic\n\ntheorem foo : True := by\n  sorry\n```"
    ]
    agent = FormalizerAgent(mock_runtime)

    result = asyncio.run(_formalize_statement(agent))

    assert result.startswith("import Mathlib.Tactic")
    assert "```" not in result
    assert mock_runtime.calls[0]["metadata"]["callsite"] == "formalizer.formalize_statement"


def test_formalizer_extracts_fenced_step_sketch(mock_runtime):
    mock_runtime._responses = [
        "```lean\nimport Mathlib.Tactic\n\nlemma step_1 : True := by\n  sorry\n```"
    ]
    agent = FormalizerAgent(mock_runtime)

    result = asyncio.run(_formalize_step_sketch(agent))

    assert result.startswith("import Mathlib.Tactic")
    assert "lemma step_1" in result
    assert mock_runtime.calls[0]["metadata"]["callsite"] == "formalizer.formalize_step_sketch"
