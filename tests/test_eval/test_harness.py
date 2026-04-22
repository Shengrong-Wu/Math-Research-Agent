import json

from math_agent.eval.harness import EvalReport, EvalResult, build_evolution_score, score_run
from math_agent.problem.spec import load_problem


def test_score_run_reads_v3_phase1_summary(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "success": True,
                "phase": "phase1_only",
                "problem_id": "harmonic_sum_not_integer",
                "roadmaps_attempted": 2,
                "crash_free": True,
                "phase1_signals": {
                    "phase1_success": True,
                    "review_passed": True,
                    "falsifier_passed": False,
                },
                "prompt_telemetry": {"calls": 9, "near_limit_calls": 1},
            }
        ),
        encoding="utf-8",
    )

    result = score_run(
        load_problem("harmonic_sum_not_integer"),
        run_dir,
        wall_clock=123.0,
    )

    assert result.phase1_success is True
    assert result.review_passed is True
    assert result.falsifier_passed is False
    assert result.correctness == "partial"
    assert result.crash_free is True
    assert result.prompt_telemetry["calls"] == 9


def test_build_evolution_score_uses_phase1_review_falsifier_and_crash_free():
    report = EvalReport(
        results=[
            EvalResult(
                problem_id="a",
                difficulty_level=4,
                difficulty_label="x",
                domain="y",
                correctness="supported",
                phase1_success=True,
                review_passed=True,
                falsifier_passed=True,
                crash_free=True,
                wall_clock_seconds=100.0,
            ),
            EvalResult(
                problem_id="b",
                difficulty_level=5,
                difficulty_label="x",
                domain="y",
                correctness="error",
                phase1_success=False,
                review_passed=False,
                falsifier_passed=False,
                crash_free=False,
                wall_clock_seconds=200.0,
            ),
        ]
    )

    score = build_evolution_score(report)

    assert score["phase1_success_rate"] == 0.5
    assert score["review_pass_rate"] == 0.5
    assert score["falsifier_pass_rate"] == 0.5
    assert score["supported_rate"] == 0.5
    assert score["crash_free_rate"] == 0.5
    assert score["efficiency_wall"] == -150.0
