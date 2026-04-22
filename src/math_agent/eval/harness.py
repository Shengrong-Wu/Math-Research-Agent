"""Evaluation harness for Math Agent v3."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from math_agent.config import AppConfig, load_config
from math_agent.orchestrator.coordinator import Coordinator
from math_agent.problem.spec import ProblemSpec, load_problem, load_suite, list_problems

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    problem_id: str
    difficulty_level: int
    difficulty_label: str
    domain: str
    correctness: str = "error"
    phase1_success: bool = False
    review_passed: bool = False
    falsifier_passed: bool = False
    crash_free: bool = True
    wall_clock_seconds: float = 0.0
    roadmaps_attempted: int = 0
    run_dir: str = ""
    timestamp: str = ""
    error_message: str = ""
    prompt_telemetry: dict[str, object] = field(default_factory=dict)


@dataclass
class EvalReport:
    results: list[EvalResult] = field(default_factory=list)
    config_summary: str = ""
    started_at: str = ""
    finished_at: str = ""

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def phase1_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.phase1_success) / len(self.results)

    @property
    def review_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.review_passed) / len(self.results)

    @property
    def falsifier_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.falsifier_passed) / len(self.results)

    @property
    def crash_free_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.crash_free) / len(self.results)

    @property
    def supported_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.correctness == "supported") / len(self.results)

    @property
    def total_wall_clock(self) -> float:
        return sum(r.wall_clock_seconds for r in self.results)

    def summary_table(self) -> str:
        lines = [
            "=" * 72,
            "  MATH AGENT V3 EVALUATION REPORT",
            f"  {self.started_at} -> {self.finished_at}",
            "=" * 72,
            f"  Total problems:     {self.total}",
            f"  Supported:          {sum(1 for r in self.results if r.correctness == 'supported')} ({self.supported_rate:.1%})",
            f"  Phase 1 pass rate:  {self.phase1_rate:.1%}",
            f"  Review pass rate:   {self.review_rate:.1%}",
            f"  Falsifier pass rate:{self.falsifier_rate:.1%}",
            f"  Crash-free rate:    {self.crash_free_rate:.1%}",
            f"  Total wall clock:   {self.total_wall_clock:.0f}s",
            "─" * 72,
        ]
        for r in sorted(self.results, key=lambda x: (x.difficulty_level, x.problem_id)):
            lines.append(
                f"  {r.problem_id:40s} {r.correctness:10s} "
                f"P1={int(r.phase1_success)} R={int(r.review_passed)} F={int(r.falsifier_passed)} "
                f"{r.wall_clock_seconds:6.0f}s {r.roadmaps_attempted}rm"
            )
        lines.append("=" * 72)
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(
            {
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "config_summary": self.config_summary,
                "summary": {
                    "total": self.total,
                    "phase1_rate": self.phase1_rate,
                    "review_rate": self.review_rate,
                    "falsifier_rate": self.falsifier_rate,
                    "crash_free_rate": self.crash_free_rate,
                    "supported_rate": self.supported_rate,
                    "total_wall_clock": self.total_wall_clock,
                },
                "results": [r.__dict__ for r in self.results],
            },
            indent=2,
        )


def score_run(
    problem: ProblemSpec,
    run_dir: Path,
    *,
    wall_clock: float,
) -> EvalResult:
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        return EvalResult(
            problem_id=problem.problem_id,
            difficulty_level=problem.difficulty_level,
            difficulty_label=problem.difficulty_label,
            domain=problem.domain,
            correctness="error",
            crash_free=False,
            wall_clock_seconds=wall_clock,
            run_dir=str(run_dir),
            error_message="Missing summary.json",
        )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    signals = summary.get("phase1_signals", {})
    phase1_success = bool(signals.get("phase1_success", summary.get("success", False)))
    review_passed = bool(signals.get("review_passed", phase1_success))
    falsifier_passed = bool(signals.get("falsifier_passed", phase1_success))
    crash_free = bool(summary.get("crash_free", True))
    correctness = "supported" if phase1_success and review_passed and falsifier_passed else (
        "partial" if phase1_success else "error"
    )
    return EvalResult(
        problem_id=problem.problem_id,
        difficulty_level=problem.difficulty_level,
        difficulty_label=problem.difficulty_label,
        domain=problem.domain,
        correctness=correctness,
        phase1_success=phase1_success,
        review_passed=review_passed,
        falsifier_passed=falsifier_passed,
        crash_free=crash_free,
        wall_clock_seconds=wall_clock,
        roadmaps_attempted=int(summary.get("roadmaps_attempted", 0)),
        run_dir=str(run_dir),
        timestamp=str(summary.get("timestamp", "")),
        error_message=str(summary.get("error_message", "")),
        prompt_telemetry=dict(summary.get("prompt_telemetry", {})),
    )


def build_evolution_score(report: EvalReport) -> dict[str, float]:
    total = max(report.total, 1)
    return {
        "phase1_success_rate": report.phase1_rate,
        "review_pass_rate": report.review_rate,
        "falsifier_pass_rate": report.falsifier_rate,
        "supported_rate": report.supported_rate,
        "crash_free_rate": report.crash_free_rate,
        "efficiency_wall": -(report.total_wall_clock / total),
    }


async def _run_problem(config: AppConfig, problem: ProblemSpec) -> EvalResult:
    started = time.perf_counter()
    coordinator = Coordinator(config=config, problem=problem)
    result = await coordinator.run()
    elapsed = time.perf_counter() - started
    if result.run_dir is None:
        return EvalResult(
            problem_id=problem.problem_id,
            difficulty_level=problem.difficulty_level,
            difficulty_label=problem.difficulty_label,
            domain=problem.domain,
            correctness="error",
            crash_free=False,
            wall_clock_seconds=elapsed,
            error_message=result.error_message or "Run directory missing",
        )
    return score_run(problem, result.run_dir, wall_clock=elapsed)


def _resolve_problems(suite: str | None, problems: list[str] | None) -> list[ProblemSpec]:
    if problems:
        return [load_problem(pid) for pid in problems]
    if suite:
        return load_suite(suite)
    return [load_problem(pid) for pid in list_problems()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Math Agent v3 eval harness")
    parser.add_argument("--config", type=Path, default=None, help="Path to config TOML")
    parser.add_argument("--suite", type=str, default=None, help="Suite name")
    parser.add_argument("--problems", nargs="*", default=None, help="Specific problem IDs")
    parser.add_argument("--resume", type=Path, default=None, help="Score existing run directories under this path")
    parser.add_argument("--lean-mode", type=str, default=None, choices=["off", "check", "full"], help="Lean mode override")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    config = load_config(args.config)
    if args.lean_mode:
        config = AppConfig(
            hyper=config.hyper,
            prompt_budgets=config.prompt_budgets,
            runtime=config.runtime,
            agents=config.agents,
            lean=config.lean,
            lean_mode="check" if args.lean_mode == "full" else args.lean_mode,
            problem_id=config.problem_id,
            suite=config.suite,
            runs_dir=config.runs_dir,
        )

    report = EvalReport(
        config_summary=f"{config.runtime.backend}/{config.runtime.model}",
        started_at=datetime.now().isoformat(timespec="seconds"),
    )

    if args.resume is not None:
        for run_dir in sorted(p for p in args.resume.iterdir() if p.is_dir()):
            summary_path = run_dir / "summary.json"
            if not summary_path.exists():
                continue
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            problem_id = summary.get("problem_id")
            if not problem_id:
                continue
            try:
                problem = load_problem(problem_id)
            except KeyError:
                problem = ProblemSpec(
                    problem_id=problem_id,
                    question=str(summary.get("problem", "")),
                    domain="general",
                    difficulty_level=4,
                    difficulty_label="custom",
                )
            report.results.append(score_run(problem, run_dir, wall_clock=0.0))
    else:
        problems = _resolve_problems(args.suite or config.suite or None, args.problems)
        for problem in problems:
            report.results.append(asyncio.run(_run_problem(config, problem)))

    report.finished_at = datetime.now().isoformat(timespec="seconds")
    print(report.summary_table())


if __name__ == "__main__":
    main()
