import asyncio

from conftest import MockRuntimeSession
from math_agent.agents.falsifier import FalsifierAgent, PythonCheckResult


def test_parse_verdict_keeps_explicit_pass_without_python_checks():
    result = FalsifierAgent._parse_verdict(
        "VERDICT: PASS\n"
        "COUNTEREXAMPLE: NONE\n"
        "MISSING_CASES: NONE\n"
        "REASONING: The proof looks correct.\n"
        "SUGGESTIONS: NONE",
        [],
    )

    assert result.verdict == "PASS"
    assert result.has_counterexample is False
    assert result.missing_cases == []


def test_parse_verdict_keeps_explicit_pass_with_failed_control_checks():
    control_check = PythonCheckResult(
        description="Negative control after dropping a hypothesis",
        code="print('FAIL: weakened hypothesis admits a counterexample')",
        stdout="FAIL: weakened hypothesis admits a counterexample\n",
        stderr="",
        passed=False,
    )

    result = FalsifierAgent._parse_verdict(
        "VERDICT: PASS\n"
        "COUNTEREXAMPLE: NONE\n"
        "MISSING_CASES: NONE\n"
        "REASONING: The original theorem survives all direct tests.\n"
        "SUGGESTIONS: NONE",
        [control_check],
    )

    assert result.verdict == "PASS"
    assert result.has_counterexample is False
    assert result.missing_cases == []


def test_parse_verdict_downgrades_pass_when_counterexample_reported():
    result = FalsifierAgent._parse_verdict(
        "VERDICT: PASS\n"
        "COUNTEREXAMPLE: A concrete counterexample exists.\n"
        "MISSING_CASES: NONE\n"
        "REASONING: Mixed signals.\n"
        "SUGGESTIONS: NONE",
        [],
    )

    assert result.verdict == "UNCERTAIN"
    assert result.has_counterexample is True


def test_falsify_prompt_discourages_weakened_hypothesis_python_tests():
    runtime = MockRuntimeSession(
        responses=[
            "No Python blocks are needed for this smoke test.",
            "VERDICT: PASS\n"
            "COUNTEREXAMPLE: NONE\n"
            "MISSING_CASES: NONE\n"
            "REASONING: No issue found.\n"
            "SUGGESTIONS: NONE",
        ],
        role="falsifier",
    )
    agent = FalsifierAgent(runtime)

    result = asyncio.run(
        agent.falsify(
            "Prove a simple implication.",
            "Claimed proof.",
            max_python_checks=0,
        )
    )

    assert result.verdict == "PASS"
    assert len(runtime.calls) == 2
    assert "Do NOT write Python tests that intentionally drop or weaken the theorem's assumptions." in runtime.calls[0]["prompt"]
