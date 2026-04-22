"""CLI entry point for Math Agent."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import replace
from pathlib import Path

from math_agent.config import (
    AgentConfigs,
    AgentRuntimeConfig,
    API_BACKENDS,
    AppConfig,
    CLI_BACKENDS,
    DEFAULT_MODELS,
    KNOWN_MODELS,
    RuntimeConfig,
    default_cli_path,
    load_config,
)
from math_agent.problem.spec import (
    ProblemSpec,
    list_problems,
    list_suites,
    load_problem,
    load_suite,
)

logger = logging.getLogger(__name__)

BACKEND_MENU = {
    "1": ("codex", "Codex CLI"),
    "2": ("claude", "Claude CLI"),
    "3": ("openai", "OpenAI API"),
    "4": ("anthropic", "Anthropic API"),
    "5": ("deepseek", "DeepSeek API"),
    "6": ("gemini", "Gemini API"),
}


def _normalize_cli_lean_mode(raw_mode: str | None) -> str | None:
    if raw_mode is None:
        return None
    mode = raw_mode.strip().lower()
    if mode == "full":
        logger.warning("--lean-mode full is deprecated; using check instead.")
        return "check"
    return mode


def _runtime_from_selection(
    backend: str,
    model: str,
    *,
    effort: str = "low",
    sandbox: str = "workspace-write",
) -> RuntimeConfig:
    return RuntimeConfig(
        backend=backend,
        model=model or DEFAULT_MODELS.get(backend, ""),
        effort=effort,
        sandbox=sandbox,
        cli_path=default_cli_path(backend),
    )


def _pick_runtime(prompt_label: str = "runtime") -> RuntimeConfig:
    print(f"\nSelect {prompt_label}:")
    for key, (_, label) in BACKEND_MENU.items():
        print(f"  {key}. {label}")
    choice = input("\nChoice [1]: ").strip() or "1"
    if choice not in BACKEND_MENU:
        choice = "1"
    backend = BACKEND_MENU[choice][0]
    default_model = DEFAULT_MODELS[backend]
    known_models = ", ".join(KNOWN_MODELS.get(backend, []))
    print(f"  Known models: {known_models}")
    model = input(f"  Model [{default_model}]: ").strip() or default_model
    if backend in CLI_BACKENDS:
        effort = input("  Effort [low]: ").strip() or "low"
        sandbox = input("  Sandbox [workspace-write]: ").strip() or "workspace-write"
        return _runtime_from_selection(
            backend,
            model,
            effort=effort,
            sandbox=sandbox,
        )
    return _runtime_from_selection(backend, model)


def select_runtimes() -> tuple[RuntimeConfig, AgentConfigs]:
    print("\nRuntime mode:")
    print("  1. Single backend for all agents")
    print("  2. Different backend per agent")
    mode = input("\nChoice [1]: ").strip() or "1"
    if mode == "2":
        print("\n--- Thinking Agent ---")
        thinking = _pick_runtime("Thinking Agent runtime")
        print("\n--- Formalizer Agent ---")
        formalizer = _pick_runtime("Formalizer Agent runtime")
        print("\n--- Assistant Agent ---")
        assistant = _pick_runtime("Assistant Agent runtime")
        print("\n--- Review Agent ---")
        review = _pick_runtime("Review Agent runtime")
        print("\n--- Falsifier Agent ---")
        falsifier = _pick_runtime("Falsifier Agent runtime")
        agents = AgentConfigs(
            thinking=AgentRuntimeConfig(
                backend=thinking.backend,
                model=thinking.model,
                effort=thinking.effort,
                temperature=thinking.temperature,
                sandbox=thinking.sandbox,
                approval_policy=thinking.approval_policy,
            ),
            formalizer=AgentRuntimeConfig(
                backend=formalizer.backend,
                model=formalizer.model,
                effort=formalizer.effort,
                temperature=formalizer.temperature,
                sandbox=formalizer.sandbox,
                approval_policy=formalizer.approval_policy,
            ),
            assistant=AgentRuntimeConfig(
                backend=assistant.backend,
                model=assistant.model,
                effort=assistant.effort,
                temperature=assistant.temperature,
                sandbox=assistant.sandbox,
                approval_policy=assistant.approval_policy,
            ),
            review=AgentRuntimeConfig(
                backend=review.backend,
                model=review.model,
                effort=review.effort,
                temperature=review.temperature,
                sandbox=review.sandbox,
                approval_policy=review.approval_policy,
            ),
            falsifier=AgentRuntimeConfig(
                backend=falsifier.backend,
                model=falsifier.model,
                effort=falsifier.effort,
                temperature=falsifier.temperature,
                sandbox=falsifier.sandbox,
                approval_policy=falsifier.approval_policy,
            ),
        )
        return thinking, agents

    return _pick_runtime("runtime"), AgentConfigs()


def select_problem() -> ProblemSpec:
    print("\nSelect problem source:")
    print("  1. Built-in problem")
    print("  2. Built-in suite")
    print("  3. Custom problem")
    choice = input("\nChoice [1]: ").strip() or "1"
    if choice == "1":
        problems = list_problems()
        print(f"\nAvailable problems ({len(problems)}):")
        for i, pid in enumerate(problems, 1):
            p = load_problem(pid)
            print(f"  {i:2d}. [{p.difficulty_label}] {pid}")
        idx = input("\nProblem number [1]: ").strip() or "1"
        try:
            return load_problem(problems[int(idx) - 1])
        except (IndexError, ValueError):
            return load_problem(problems[0])
    if choice == "2":
        suites = list_suites()
        print(f"\nAvailable suites ({len(suites)}):")
        for i, (name, pids) in enumerate(suites.items(), 1):
            print(f"  {i}. {name} ({len(pids)} problems)")
        idx = input("\nSuite number [1]: ").strip() or "1"
        suite_names = list(suites.keys())
        try:
            suite_name = suite_names[int(idx) - 1]
        except (IndexError, ValueError):
            suite_name = suite_names[0]
        return load_suite(suite_name)[0]
    question = input("\nEnter your math problem:\n> ").strip()
    domain = input("Domain [general]: ").strip() or "general"
    return ProblemSpec(
        problem_id="custom",
        question=question,
        domain=domain,
        difficulty_level=4,
        difficulty_label="custom",
    )


def ask_lean_mode() -> str:
    print("\nLean verification mode:")
    print("  [1] Off   — pure proof search, no Lean checks")
    print("  [2] Check — statement and sketch verification during Phase 1")
    choice = input("Choose [1/2] (default: 1): ").strip()
    return {"1": "off", "2": "check"}.get(choice, "off")


def _offer_resume(runs_dir: Path) -> bool:
    if not runs_dir.is_dir():
        return False
    runs = [
        d
        for d in sorted(runs_dir.iterdir(), reverse=True)
        if d.is_dir() and not d.name.startswith(".") and (d / "summary.json").exists()
    ]
    return bool(runs) and input("\nResume from a previous run? [y/N]: ").strip().lower() in ("y", "yes")


def _interactive_resume(runs_dir: Path) -> tuple[Path | None, ProblemSpec | None]:
    runs = []
    for d in sorted(runs_dir.iterdir(), reverse=True):
        if not d.is_dir() or d.name.startswith("."):
            continue
        summary_path = d / "summary.json"
        if not summary_path.exists():
            continue
        info: dict = {"path": d, "name": d.name}
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        info["problem_id"] = summary.get("problem_id", "?")
        info["success"] = summary.get("success", False)
        info["roadmaps"] = summary.get(
            "roadmaps_attempted",
            summary.get("total_roadmaps", 0),
        )
        runs.append(info)
    if not runs:
        return None, None
    print(f"\nPrevious runs ({len(runs)}):")
    for i, r in enumerate(runs[:20], 1):
        status = "OK" if r.get("success") else "FAIL"
        print(
            f"  {i:2d}. {r['name']}  [{status}]  "
            f"{r.get('problem_id', '?')}  ({r.get('roadmaps', '?')} roadmaps)"
        )
    choice = input("\nRun number to resume (or Enter to skip): ").strip()
    if not choice:
        return None, None
    try:
        selected = runs[int(choice) - 1]
    except (IndexError, ValueError):
        return None, None
    resume_path = selected["path"]
    summary = json.loads((resume_path / "summary.json").read_text(encoding="utf-8"))
    prev_pid = summary.get("problem_id", "")
    prev_question = summary.get("problem", "")
    if prev_pid and prev_pid != "custom":
        try:
            return resume_path, load_problem(prev_pid)
        except KeyError:
            pass
    if prev_question:
        return resume_path, ProblemSpec(
            problem_id=prev_pid or "custom",
            question=prev_question,
            domain="general",
            difficulty_level=4,
            difficulty_label="custom",
        )
    return resume_path, None


async def run_agent(
    config: AppConfig,
    problem: ProblemSpec,
    resume_from: Path | None = None,
) -> None:
    from math_agent.orchestrator.coordinator import Coordinator

    coordinator = Coordinator(config=config, problem=problem, resume_from=resume_from)

    def on_event(event):
        step_index = getattr(event, "step_index", None)
        prefix = f"step {step_index}" if step_index is not None else "run"
        extras: list[str] = []
        metadata = getattr(event, "metadata", {}) or {}
        if "worker_assembly_profile" in metadata:
            extras.append(f"worker={metadata['worker_assembly_profile']}")
        if "assembly_profile" in metadata:
            extras.append(f"planner={metadata['assembly_profile']}")
        if "review_assembly_profile" in metadata:
            extras.append(f"review={metadata['review_assembly_profile']}")
        if "falsifier_assembly_profile" in metadata:
            extras.append(f"falsifier={metadata['falsifier_assembly_profile']}")
        if metadata.get("trigger"):
            extras.append(f"trigger={metadata['trigger']}")
        suffix = f" [{' | '.join(extras)}]" if extras else ""
        print(f"  [{event.event_type}] {prefix}{suffix}: {event.content[:200]}")

    coordinator.on_event(on_event)

    print(f"\n{'=' * 60}")
    if resume_from:
        print(f"RESUMING from: {resume_from.name}")
    print(f"Problem: {problem.question[:80]}...")
    print(f"Domain:  {problem.domain} | Difficulty: {problem.difficulty_label}")
    print(f"Lean:    {config.lean_mode}")
    print(f"{'─' * 60}")
    for role, acfg in [
        ("Thinking  ", config.agents.thinking),
        ("Formalizer", config.agents.formalizer),
        ("Assistant ", config.agents.assistant),
        ("Review    ", config.agents.review),
        ("Falsifier ", config.agents.falsifier),
    ]:
        backend = acfg.backend or config.runtime.backend
        model = acfg.model or config.runtime.model or DEFAULT_MODELS.get(backend, "")
        print(f"  {role}  {backend} / {model}")
    print(f"{'=' * 60}\n")

    result = await coordinator.run()

    print(f"\n{'=' * 60}")
    if result.success:
        print(f"SUCCESS after {result.total_roadmaps} roadmap(s)")
    else:
        print(f"FAILED after {result.total_roadmaps} roadmap(s)")
    if result.run_dir:
        print(f"Run directory: {result.run_dir}")
    if result.error_message:
        print(f"Error: {result.error_message}")
    if result.prompt_telemetry:
        telemetry = result.prompt_telemetry
        print(
            "Prompt usage: "
            f"{telemetry.get('calls', 0)} call(s), "
            f"max {telemetry.get('max_prompt_chars', 0)} chars "
            f"(~{telemetry.get('max_prompt_tokens_estimate', 0)} tok), "
            f"near-limit {telemetry.get('near_limit_calls', 0)}, "
            f"retried {telemetry.get('retried_calls', 0)}."
        )
    print(f"{'=' * 60}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Math Agent -- proof search with CLI and API runtimes",
    )
    parser.add_argument("--config", type=Path, default=None, help="Path to config TOML file")
    parser.add_argument("--problem", type=str, default=None, help="Built-in problem ID to solve")
    parser.add_argument("--suite", type=str, default=None, help="Built-in suite name")
    parser.add_argument("--question", type=str, default=None, help="Custom problem statement")
    parser.add_argument("--domain", type=str, default="general", help="Domain for custom problems")
    parser.add_argument(
        "--backend",
        type=str,
        default=None,
        choices=sorted(CLI_BACKENDS | API_BACKENDS),
        help="Shared backend",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Deprecated alias for --backend when choosing an API provider",
    )
    parser.add_argument("--model", type=str, default=None, help="Shared model")
    parser.add_argument("--effort", type=str, default=None, help="Shared reasoning effort")
    parser.add_argument("--sandbox", type=str, default=None, help="Shared sandbox mode")
    parser.add_argument("--approval-policy", type=str, default=None, help="Shared approval policy")
    parser.add_argument(
        "--lean-mode",
        type=str,
        default=None,
        choices=["off", "check", "full"],
        help="Lean mode: off/check/full (full is normalized to check)",
    )
    parser.add_argument(
        "--skip-lean",
        action="store_true",
        default=False,
        help="Deprecated alias for --lean-mode off",
    )
    parser.add_argument("--resume", type=str, default=None, help="Resume from a previous run dir")
    parser.add_argument("--eval", action="store_true", default=False, help="Run eval harness")
    parser.add_argument("--eval-suite", type=str, default=None, help="Eval suite name")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.eval:
        from math_agent.eval.harness import main as eval_main
        import sys as _sys

        eval_argv = []
        if args.config:
            eval_argv.extend(["--config", str(args.config)])
        if args.eval_suite:
            eval_argv.extend(["--suite", args.eval_suite])
        if args.lean_mode or args.skip_lean:
            lean_mode = "off" if args.skip_lean else _normalize_cli_lean_mode(args.lean_mode)
            eval_argv.extend(["--lean-mode", lean_mode])
        _sys.argv = ["math_agent.eval.harness"] + eval_argv
        eval_main()
        return

    config = load_config(args.config)

    selected_backend = args.backend
    if args.provider and not args.backend:
        logger.warning("--provider is deprecated; treating %s as --backend.", args.provider)
        selected_backend = args.provider
    elif args.provider and args.backend and args.provider != args.backend:
        logger.warning("--provider=%s ignored because --backend=%s was also passed.", args.provider, args.backend)

    if any([selected_backend, args.model, args.effort, args.sandbox, args.approval_policy]):
        new_backend = selected_backend or config.runtime.backend
        backend_changed = new_backend != config.runtime.backend
        config = replace(
            config,
            runtime=replace(
                config.runtime,
                backend=new_backend,
                model=(
                    args.model
                    or (
                        DEFAULT_MODELS.get(new_backend, "")
                        if backend_changed
                        else config.runtime.model
                    )
                    or DEFAULT_MODELS.get(new_backend, "")
                ),
                effort=args.effort or config.runtime.effort,
                sandbox=args.sandbox or config.runtime.sandbox,
                approval_policy=args.approval_policy or config.runtime.approval_policy,
                cli_path=(
                    config.runtime.cli_path
                    if not backend_changed
                    else default_cli_path(new_backend)
                ),
            ),
        )

    if args.skip_lean:
        config = replace(config, lean_mode="off")
    elif args.lean_mode:
        config = replace(
            config,
            lean_mode=_normalize_cli_lean_mode(args.lean_mode) or config.lean_mode,
        )

    resume_from: Path | None = None
    if args.resume:
        candidate = Path(args.resume)
        if not candidate.is_absolute() and not candidate.is_dir():
            candidate = config.runs_dir / args.resume
        if not candidate.is_dir():
            raise SystemExit(f"Run directory not found: {candidate}")
        resume_from = candidate

    if args.problem:
        problem = load_problem(args.problem)
    elif args.suite:
        problem = load_suite(args.suite)[0]
    elif args.question:
        problem = ProblemSpec(
            problem_id="custom",
            question=args.question,
            domain=args.domain,
            difficulty_level=4,
            difficulty_label="custom",
        )
    elif resume_from:
        summary = json.loads((resume_from / "summary.json").read_text(encoding="utf-8"))
        prev_pid = summary.get("problem_id", "")
        prev_question = summary.get("problem", "")
        if prev_pid and prev_pid != "custom":
            try:
                problem = load_problem(prev_pid)
            except KeyError:
                problem = ProblemSpec(
                    problem_id=prev_pid,
                    question=prev_question,
                    domain="general",
                    difficulty_level=4,
                    difficulty_label="unknown",
                )
        else:
            problem = ProblemSpec(
                problem_id=prev_pid or "custom",
                question=prev_question,
                domain="general",
                difficulty_level=4,
                difficulty_label="custom",
            )
    else:
        runtime, agents = select_runtimes()
        if _offer_resume(config.runs_dir):
            resume_from, prev_problem = _interactive_resume(config.runs_dir)
            problem = prev_problem or select_problem()
        else:
            problem = select_problem()
        lean_mode = ask_lean_mode() if config.lean_mode == "off" else config.lean_mode
        config = replace(config, runtime=runtime, agents=agents, lean_mode=lean_mode)

    asyncio.run(run_agent(config, problem, resume_from=resume_from))


if __name__ == "__main__":
    main()
