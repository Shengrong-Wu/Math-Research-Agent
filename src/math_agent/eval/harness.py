"""Evaluation harness: run a set of problems and score results.

Usage:
    python -m math_agent.eval.harness                # run default eval suite
    python -m math_agent.eval.harness --suite demo    # run a named suite
    python -m math_agent.eval.harness --problems p1 p2  # specific problems
    python -m math_agent.eval.harness --resume runs/  # score existing runs
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from math_agent.config import AppConfig, load_config
from math_agent.problem.spec import (
    ProblemSpec,
    load_problem,
    load_suite,
    list_problems,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class EvalResult:
    """Scored result for a single problem run."""

    problem_id: str
    difficulty_level: int
    difficulty_label: str
    domain: str

    # Outcome
    correctness: Literal["correct", "incomplete", "wrong", "error", "timeout"] = "error"
    phase1_success: bool = False
    phase2_success: bool = False
    sufficiency: bool = False  # did the proof establish both directions?

    # Cost metrics
    tokens_used: int = 0
    wall_clock_seconds: float = 0.0
    roadmaps_attempted: int = 0
    modules_completed: int = 0
    modules_failed: int = 0
    external_claims: int = 0

    # Run metadata
    run_dir: str = ""
    timestamp: str = ""
    error_message: str = ""
    complete_proof: str = ""


@dataclass
class EvalReport:
    """Aggregate report across all problem runs."""

    results: list[EvalResult] = field(default_factory=list)
    config_summary: str = ""
    started_at: str = ""
    finished_at: str = ""

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def correct(self) -> int:
        return sum(1 for r in self.results if r.correctness == "correct")

    @property
    def incomplete(self) -> int:
        return sum(1 for r in self.results if r.correctness == "incomplete")

    @property
    def wrong(self) -> int:
        return sum(1 for r in self.results if r.correctness == "wrong")

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.correctness in ("error", "timeout"))

    @property
    def phase1_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.phase1_success) / len(self.results)

    @property
    def phase2_rate(self) -> float:
        p1_passed = [r for r in self.results if r.phase1_success]
        if not p1_passed:
            return 0.0
        return sum(1 for r in p1_passed if r.phase2_success) / len(p1_passed)

    @property
    def total_tokens(self) -> int:
        return sum(r.tokens_used for r in self.results)

    @property
    def total_wall_clock(self) -> float:
        return sum(r.wall_clock_seconds for r in self.results)

    def by_difficulty(self) -> dict[int, list[EvalResult]]:
        """Group results by difficulty level."""
        groups: dict[int, list[EvalResult]] = {}
        for r in self.results:
            groups.setdefault(r.difficulty_level, []).append(r)
        return dict(sorted(groups.items()))

    def by_domain(self) -> dict[str, list[EvalResult]]:
        """Group results by domain."""
        groups: dict[str, list[EvalResult]] = {}
        for r in self.results:
            groups.setdefault(r.domain, []).append(r)
        return dict(sorted(groups.items()))

    def summary_table(self) -> str:
        """Render a human-readable summary table."""
        lines: list[str] = []
        lines.append(f"{'=' * 72}")
        lines.append(f"  EVALUATION REPORT")
        lines.append(f"  {self.started_at} -> {self.finished_at}")
        lines.append(f"{'=' * 72}")
        lines.append(f"  Total problems:    {self.total}")
        lines.append(f"  Correct:           {self.correct} ({self._pct(self.correct)})")
        lines.append(f"  Incomplete:        {self.incomplete} ({self._pct(self.incomplete)})")
        lines.append(f"  Wrong:             {self.wrong} ({self._pct(self.wrong)})")
        lines.append(f"  Errors/Timeout:    {self.errors} ({self._pct(self.errors)})")
        lines.append(f"  Phase 1 pass rate: {self.phase1_rate:.1%}")
        lines.append(f"  Phase 2 pass rate: {self.phase2_rate:.1%}")
        lines.append(f"  Total tokens:      {self.total_tokens:,}")
        lines.append(f"  Total wall clock:  {self.total_wall_clock:.0f}s")
        lines.append(f"{'─' * 72}")

        # By difficulty
        lines.append(f"  BY DIFFICULTY:")
        for level, group in self.by_difficulty().items():
            correct = sum(1 for r in group if r.correctness == "correct")
            lines.append(f"    L{level}: {correct}/{len(group)} correct")

        # By domain
        lines.append(f"  BY DOMAIN:")
        for domain, group in self.by_domain().items():
            correct = sum(1 for r in group if r.correctness == "correct")
            lines.append(f"    {domain}: {correct}/{len(group)} correct")

        lines.append(f"{'─' * 72}")

        # Per-problem detail
        lines.append(f"  DETAILS:")
        for r in sorted(self.results, key=lambda x: (x.difficulty_level, x.problem_id)):
            status = r.correctness.upper()
            phase = "P1" if r.phase1_success else "--"
            phase += "+P2" if r.phase2_success else "+--"
            lines.append(
                f"    [{status:10s}] L{r.difficulty_level} {r.problem_id:40s} "
                f"{phase:6s} {r.wall_clock_seconds:6.0f}s {r.roadmaps_attempted}rm"
            )

        lines.append(f"{'=' * 72}")
        return "\n".join(lines)

    def _pct(self, count: int) -> str:
        if self.total == 0:
            return "0%"
        return f"{count / self.total:.0%}"

    def to_json(self) -> str:
        """Serialize the full report to JSON."""
        data = {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "config_summary": self.config_summary,
            "summary": {
                "total": self.total,
                "correct": self.correct,
                "incomplete": self.incomplete,
                "wrong": self.wrong,
                "errors": self.errors,
                "phase1_rate": self.phase1_rate,
                "phase2_rate": self.phase2_rate,
                "total_tokens": self.total_tokens,
                "total_wall_clock": self.total_wall_clock,
            },
            "results": [
                {
                    "problem_id": r.problem_id,
                    "difficulty_level": r.difficulty_level,
                    "difficulty_label": r.difficulty_label,
                    "domain": r.domain,
                    "correctness": r.correctness,
                    "phase1_success": r.phase1_success,
                    "phase2_success": r.phase2_success,
                    "sufficiency": r.sufficiency,
                    "tokens_used": r.tokens_used,
                    "wall_clock_seconds": r.wall_clock_seconds,
                    "roadmaps_attempted": r.roadmaps_attempted,
                    "modules_completed": r.modules_completed,
                    "modules_failed": r.modules_failed,
                    "external_claims": r.external_claims,
                    "run_dir": r.run_dir,
                    "timestamp": r.timestamp,
                    "error_message": r.error_message,
                }
                for r in self.results
            ],
        }
        return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Default eval suite (spanning L1-L5)
# ---------------------------------------------------------------------------

EVAL_SUITE: list[str] = [
    # L1 - toy (4)
    "sum_first_n_odds",
    "square_expansion_commutative_ring",
    "difference_of_squares_commutative_ring",
    "difference_of_cubes_commutative_ring",
    # L2 - toy (1)
    "harmonic_sum_not_integer",
    # L3 - phd_qe (4)
    "pid_prime_implies_maximal",
    "nakayama_zero_module_local",
    "compact_to_hausdorff_homeomorphism",
    "nonabelian_group_conjugacy_class_ratio",
    # L4 - beyond_qe (4)
    "hilbert_basis_theorem",
    "chinese_remainder_comaximal",
    "finite_dimensional_normed_space_complete",
    "imo2024_n1_divisor_plus_one",
    # L5 - research (2)
    "weak_nullstellensatz",
    "krull_intersection_theorem_local",
]


# ---------------------------------------------------------------------------
# Scorer: grade a run's output
# ---------------------------------------------------------------------------

def score_run(
    problem: ProblemSpec,
    run_dir: Path,
    *,
    wall_clock: float = 0.0,
) -> EvalResult:
    """Score a completed run based on its output files.

    Reads ``summary.json`` and the complete proof from the run directory
    to determine correctness. This is a heuristic scorer -- it uses
    structural signals (Phase 1/2 success, external claims count) rather
    than manual grading.

    For a more precise evaluation, use the falsifier agent to check
    correctness programmatically.
    """
    result = EvalResult(
        problem_id=problem.problem_id,
        difficulty_level=problem.difficulty_level,
        difficulty_label=problem.difficulty_label,
        domain=problem.domain,
        run_dir=str(run_dir),
        wall_clock_seconds=wall_clock,
    )

    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        result.correctness = "error"
        result.error_message = "No summary.json found"
        return result

    try:
        summary = json.loads(summary_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        result.correctness = "error"
        result.error_message = f"Cannot read summary.json: {exc}"
        return result

    result.timestamp = summary.get("timestamp", "")
    result.roadmaps_attempted = summary.get("total_roadmaps", 0)

    # Phase 1
    if summary.get("success"):
        result.phase1_success = True
    elif summary.get("phase") == "phase1_only" and summary.get("success"):
        result.phase1_success = True

    # Phase 2
    modules_completed = summary.get("modules_completed", [])
    external_claims = summary.get("external_claims", [])
    result.modules_completed = len(modules_completed)
    result.external_claims = len(external_claims)

    if result.phase1_success and modules_completed:
        result.phase2_success = True

    # Read complete proof if available
    notes_path = run_dir / "NOTES.md"
    if notes_path.exists():
        result.complete_proof = notes_path.read_text()

    # Score correctness heuristically
    if not result.phase1_success:
        result.correctness = "error"
        result.error_message = "Phase 1 failed"
    elif result.phase2_success and result.external_claims == 0:
        result.correctness = "correct"
    elif result.phase2_success and result.external_claims > 0:
        result.correctness = "incomplete"
        result.error_message = f"{result.external_claims} external claim(s)"
    elif result.phase1_success and not result.phase2_success:
        # Phase 1 passed but Phase 2 failed -- proof might be correct
        # but couldn't be formalized
        skip_lean = summary.get("skip_lean", False)
        if skip_lean:
            # Phase 1 only mode -- we can't assess correctness beyond
            # the contextual review
            result.correctness = "incomplete"
            result.error_message = "Phase 1 only (no Lean verification)"
        else:
            result.correctness = "incomplete"
            result.error_message = "Phase 2 formalization failed"
    else:
        result.correctness = "error"

    return result


# ---------------------------------------------------------------------------
# Runner: execute problems and collect results
# ---------------------------------------------------------------------------

async def run_single_problem(
    problem: ProblemSpec,
    config: AppConfig,
) -> EvalResult:
    """Run a single problem through the full pipeline and score it.

    Returns an EvalResult with timing and correctness assessment.
    """
    from math_agent.orchestrator.coordinator import Coordinator

    logger.info("Eval: starting problem %s (L%d)", problem.problem_id, problem.difficulty_level)

    start = time.monotonic()
    result = EvalResult(
        problem_id=problem.problem_id,
        difficulty_level=problem.difficulty_level,
        difficulty_label=problem.difficulty_label,
        domain=problem.domain,
    )

    try:
        coordinator = Coordinator(config=config, problem=problem)
        run_result = await coordinator.run()

        elapsed = time.monotonic() - start
        result.wall_clock_seconds = elapsed
        result.roadmaps_attempted = run_result.total_roadmaps

        if run_result.run_dir:
            result.run_dir = str(run_result.run_dir)
            scored = score_run(problem, run_result.run_dir, wall_clock=elapsed)
            # Copy scored fields
            result.correctness = scored.correctness
            result.phase1_success = scored.phase1_success
            result.phase2_success = scored.phase2_success
            result.sufficiency = scored.sufficiency
            result.modules_completed = scored.modules_completed
            result.modules_failed = scored.modules_failed
            result.external_claims = scored.external_claims
            result.error_message = scored.error_message
            result.complete_proof = scored.complete_proof
        else:
            result.correctness = "error"
            result.error_message = "No run directory produced"

    except asyncio.TimeoutError:
        result.correctness = "timeout"
        result.wall_clock_seconds = time.monotonic() - start
        result.error_message = "Timed out"
    except Exception as exc:
        result.correctness = "error"
        result.wall_clock_seconds = time.monotonic() - start
        result.error_message = str(exc)
        logger.exception("Eval: problem %s raised an exception", problem.problem_id)

    logger.info(
        "Eval: %s -> %s (%.0fs, %d roadmaps)",
        problem.problem_id,
        result.correctness,
        result.wall_clock_seconds,
        result.roadmaps_attempted,
    )
    return result


async def run_eval(
    problem_ids: list[str] | None = None,
    suite_name: str | None = None,
    config: AppConfig | None = None,
    *,
    timeout_per_problem: float = 1800.0,  # 30 min per problem
) -> EvalReport:
    """Run the evaluation harness across a set of problems.

    Problems are run sequentially (to avoid resource contention with
    Lean compilation and LLM rate limits).

    Args:
        problem_ids: Explicit list of problem IDs. If None, uses EVAL_SUITE.
        suite_name: Named suite to load. Overrides problem_ids.
        config: Application config. If None, loads default.
        timeout_per_problem: Max seconds per problem before timeout.

    Returns:
        An EvalReport with per-problem results and aggregate statistics.
    """
    if config is None:
        config = load_config()

    # Resolve problem list
    if suite_name:
        problems = load_suite(suite_name)
    elif problem_ids:
        problems = [load_problem(pid) for pid in problem_ids]
    else:
        problems = [load_problem(pid) for pid in EVAL_SUITE]

    report = EvalReport(
        started_at=datetime.now().isoformat(),
        config_summary=f"provider={config.provider.name} model={config.provider.model}",
    )

    logger.info("Eval: running %d problems", len(problems))

    for problem in problems:
        try:
            result = await asyncio.wait_for(
                run_single_problem(problem, config),
                timeout=timeout_per_problem,
            )
        except asyncio.TimeoutError:
            result = EvalResult(
                problem_id=problem.problem_id,
                difficulty_level=problem.difficulty_level,
                difficulty_label=problem.difficulty_label,
                domain=problem.domain,
                correctness="timeout",
                wall_clock_seconds=timeout_per_problem,
                error_message=f"Exceeded {timeout_per_problem}s timeout",
            )
        report.results.append(result)

    report.finished_at = datetime.now().isoformat()
    return report


async def score_existing_runs(
    runs_dir: Path,
    config: AppConfig | None = None,
) -> EvalReport:
    """Score existing run directories without re-running problems.

    Scans *runs_dir* for subdirectories containing ``summary.json`` and
    scores each one.

    Args:
        runs_dir: Root directory containing timestamped run folders.
        config: Optional config (for report metadata).

    Returns:
        An EvalReport with scored results.
    """
    report = EvalReport(
        started_at=datetime.now().isoformat(),
        config_summary="(scored from existing runs)",
    )

    if not runs_dir.is_dir():
        logger.warning("Runs directory not found: %s", runs_dir)
        return report

    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        summary_path = run_dir / "summary.json"
        if not summary_path.exists():
            continue

        try:
            summary = json.loads(summary_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        problem_id = summary.get("problem_id", "")
        if not problem_id:
            continue

        try:
            problem = load_problem(problem_id)
        except KeyError:
            # Unknown problem (custom or removed)
            problem = ProblemSpec(
                problem_id=problem_id,
                question=summary.get("problem", ""),
                domain="unknown",
            )

        result = score_run(problem, run_dir)
        report.results.append(result)

    report.finished_at = datetime.now().isoformat()
    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point for the eval harness."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Math Agent evaluation harness",
    )
    parser.add_argument(
        "--suite", type=str, default=None,
        help="Named problem suite to run (e.g., 'demo', 'qualifying_exam')",
    )
    parser.add_argument(
        "--problems", nargs="+", type=str, default=None,
        help="Specific problem IDs to run",
    )
    parser.add_argument(
        "--resume", type=Path, default=None,
        help="Score existing runs in this directory (no re-execution)",
    )
    parser.add_argument(
        "--config", type=Path, default=None,
        help="Path to config TOML file",
    )
    parser.add_argument(
        "--skip-lean", action="store_true", default=False,
        help="Run Phase 1 only (skip Lean formalization)",
    )
    parser.add_argument(
        "--timeout", type=float, default=1800.0,
        help="Timeout per problem in seconds (default: 1800)",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Write JSON report to this file",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    config = load_config(args.config)

    if args.skip_lean:
        from dataclasses import replace
        config = replace(config, skip_lean=True)

    async def _run():
        if args.resume:
            return await score_existing_runs(args.resume, config)
        return await run_eval(
            problem_ids=args.problems,
            suite_name=args.suite,
            config=config,
            timeout_per_problem=args.timeout,
        )

    report = asyncio.run(_run())

    # Print summary
    print(report.summary_table())

    # Write JSON report
    if args.output:
        args.output.write_text(report.to_json())
        print(f"\nJSON report written to: {args.output}")
    else:
        # Default output path
        eval_dir = Path("eval_reports")
        eval_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = eval_dir / f"eval_{ts}.json"
        out_path.write_text(report.to_json())
        print(f"\nJSON report written to: {out_path}")


if __name__ == "__main__":
    main()
