"""CLI entry point with interactive wizard for the Math Agent."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import logging
from pathlib import Path

from math_agent.config import (
    load_config,
    AppConfig,
    ProviderConfig,
    AgentConfigs,
    AgentProvider,
    DEFAULT_MODELS,
    API_KEY_ENVS,
)
from math_agent.problem.spec import (
    load_problem,
    list_problems,
    list_suites,
    load_suite,
    ProblemSpec,
)

logger = logging.getLogger(__name__)

PROVIDER_MENU = {
    "1": ("anthropic", "Anthropic (Claude Opus 4)"),
    "2": ("openai", "OpenAI (o3)"),
    "3": ("deepseek", "DeepSeek (Reasoner)"),
    "4": ("gemini", "Google (Gemini 2.5 Pro)"),
}


# ---------------------------------------------------------------------------
# Interactive helpers
# ---------------------------------------------------------------------------

def _pick_provider(prompt_label: str = "provider") -> tuple[str, str, str]:
    """Interactive single-provider picker.  Returns (name, model, api_key)."""
    print(f"\nSelect {prompt_label}:")
    for k, (_, label) in PROVIDER_MENU.items():
        print(f"  {k}. {label}")
    choice = input("\nChoice [1]: ").strip() or "1"
    if choice not in PROVIDER_MENU:
        print(f"Invalid choice '{choice}', using Anthropic.")
        choice = "1"

    name = PROVIDER_MENU[choice][0]
    default_model = DEFAULT_MODELS[name]
    model = input(f"  Model [{default_model}]: ").strip() or default_model

    env_key = API_KEY_ENVS.get(name, "")
    api_key = os.environ.get(env_key, "")
    if not api_key:
        api_key = input(f"  API key ({env_key}): ").strip()

    return name, model, api_key


def select_providers() -> tuple[ProviderConfig, AgentConfigs, dict[str, str]]:
    """Interactive provider selection.

    Returns (shared_provider, agent_configs, api_keys_by_provider).

    The user can choose:
      (a) one provider+model for all agents, or
      (b) different provider+model per agent.
    """
    print("\nProvider mode:")
    print("  1. Single provider for all agents")
    print("  2. Different provider per agent")
    mode = input("\nChoice [1]: ").strip() or "1"

    api_keys: dict[str, str] = {}

    if mode == "2":
        print("\n--- Thinking Agent (proof reasoning, needs strongest model) ---")
        t_name, t_model, t_key = _pick_provider("Thinking Agent provider")
        api_keys[t_name] = t_key

        print("\n--- Assistant Agent (MEMO/NOTES compression, can be fast+cheap) ---")
        a_name, a_model, a_key = _pick_provider("Assistant Agent provider")
        api_keys.setdefault(a_name, a_key)

        print("\n--- Review Agent (independent review, moderate strength) ---")
        r_name, r_model, r_key = _pick_provider("Review Agent provider")
        api_keys.setdefault(r_name, r_key)

        print("\n--- CLI Agent (Lean 4 code, needs good code model) ---")
        c_name, c_model, c_key = _pick_provider("CLI Agent provider")
        api_keys.setdefault(c_name, c_key)

        print("\n--- Falsifier Agent (blind checker, moderate strength) ---")
        f_name, f_model, f_key = _pick_provider("Falsifier Agent provider")
        api_keys.setdefault(f_name, f_key)

        # Use the thinking agent's provider as the shared default
        shared = ProviderConfig(name=t_name, model=t_model, temperature=0.7)
        agents = AgentConfigs(
            thinking=AgentProvider(name=t_name, model=t_model),
            assistant=AgentProvider(name=a_name, model=a_model),
            review=AgentProvider(name=r_name, model=r_model),
            cli=AgentProvider(name=c_name, model=c_model),
            falsifier=AgentProvider(name=f_name, model=f_model),
        )
        return shared, agents, api_keys

    # Single provider mode
    name, model, api_key = _pick_provider("provider")
    api_keys[name] = api_key
    shared = ProviderConfig(name=name, model=model, temperature=0.7)
    agents = AgentConfigs()  # all empty -> inherit shared
    return shared, agents, api_keys


def select_problem() -> ProblemSpec:
    """Interactive problem selection."""
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
            print("Invalid choice, using first problem.")
            return load_problem(problems[0])

    elif choice == "2":
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
        suite_problems = load_suite(suite_name)
        print(f"\nRunning suite '{suite_name}' with {len(suite_problems)} problems.")
        return suite_problems[0]

    else:
        question = input("\nEnter your math problem:\n> ").strip()
        domain = input("Domain [general]: ").strip() or "general"
        return ProblemSpec(
            problem_id="custom",
            question=question,
            domain=domain,
            difficulty_level=3,
            difficulty_label="custom",
        )


def ask_skip_lean() -> bool:
    """Ask whether to skip Phase 2 (Lean formalization)."""
    choice = input("\nSkip Lean formalization (Phase 2)? [y/N]: ").strip().lower()
    return choice in ("y", "yes")


def _offer_resume(runs_dir: Path) -> bool:
    """Check if there are previous runs and ask whether to resume."""
    if not runs_dir.is_dir():
        return False
    runs = [d for d in sorted(runs_dir.iterdir(), reverse=True)
            if d.is_dir() and not d.name.startswith(".")
            and ((d / "MEMO.json").exists() or (d / "MEMO.md").exists())]
    if not runs:
        return False
    choice = input("\nResume from a previous run? [y/N]: ").strip().lower()
    return choice in ("y", "yes")


def _interactive_resume(runs_dir: Path) -> tuple[Path | None, ProblemSpec | None]:
    """Show previous runs and let the user pick one to resume from.

    Returns ``(resume_from_path, problem)`` or ``(None, None)`` if cancelled.
    """
    runs = []
    for d in sorted(runs_dir.iterdir(), reverse=True):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if not ((d / "MEMO.json").exists() or (d / "MEMO.md").exists()):
            continue
        info: dict = {"path": d, "name": d.name}
        summary_path = d / "summary.json"
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                info["problem_id"] = summary.get("problem_id", "?")
                info["success"] = summary.get("success", False)
                info["roadmaps"] = summary.get("total_roadmaps", 0)
            except (json.JSONDecodeError, OSError):
                info["problem_id"] = "?"
        else:
            info["problem_id"] = "?"
        runs.append(info)

    if not runs:
        print("  No previous runs with MEMO found.")
        return None, None

    print(f"\nPrevious runs ({len(runs)}):")
    for i, r in enumerate(runs[:20], 1):
        status = "OK" if r.get("success") else "FAIL" if "success" in r else "?"
        roadmaps = r.get("roadmaps", "?")
        pid = r.get("problem_id", "?")
        print(f"  {i:2d}. {r['name']}  [{status}]  {pid}  ({roadmaps} roadmaps)")

    choice = input("\nRun number to resume (or Enter to skip): ").strip()
    if not choice:
        return None, None

    try:
        selected = runs[int(choice) - 1]
    except (IndexError, ValueError):
        print("Invalid choice, skipping resume.")
        return None, None

    resume_path = selected["path"]
    print(f"  Resuming from: {resume_path.name}")

    # Try to load the problem
    problem: ProblemSpec | None = None
    summary_path = resume_path / "summary.json"
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            prev_pid = summary.get("problem_id", "")
            prev_question = summary.get("problem", "")
            if prev_pid and prev_pid != "custom":
                try:
                    problem = load_problem(prev_pid)
                except KeyError:
                    if prev_question:
                        problem = ProblemSpec(
                            problem_id=prev_pid,
                            question=prev_question,
                            domain="general",
                            difficulty_level=3,
                            difficulty_label="unknown",
                        )
            elif prev_question:
                problem = ProblemSpec(
                    problem_id=prev_pid or "custom",
                    question=prev_question,
                    domain="general",
                    difficulty_level=3,
                    difficulty_label="custom",
                )
        except (json.JSONDecodeError, OSError):
            pass

    if problem:
        print(f"  Problem: {problem.question[:80]}...")
        use_same = input("  Use same problem? [Y/n]: ").strip().lower()
        if use_same in ("n", "no"):
            problem = None

    return resume_path, problem


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run_agent(
    config: AppConfig,
    problem: ProblemSpec,
    resume_from: Path | None = None,
) -> None:
    """Run the full agent pipeline for a single problem."""
    from math_agent.orchestrator.coordinator import Coordinator

    coordinator = Coordinator(
        config=config, problem=problem, resume_from=resume_from,
    )

    def on_event(event):
        prefix = (
            getattr(event, "module_name", "")
            or f"step {getattr(event, 'step_index', '?')}"
        )
        print(f"  [{event.event_type}] {prefix}: {event.content[:200]}")

    coordinator.on_event(on_event)

    # Print run header
    agents_cfg = config.agents
    shared = config.provider

    print(f"\n{'=' * 60}")
    if resume_from:
        print(f"RESUMING from: {resume_from.name}")
    print(f"Problem: {problem.question[:80]}...")
    print(f"Domain:  {problem.domain} | Difficulty: {problem.difficulty_label}")
    print(f"Phase 2: {'SKIP (math proof only)' if config.skip_lean else 'Lean 4 formalization'}")
    print(f"{'─' * 60}")
    for role, acfg in [
        ("Thinking  ", agents_cfg.thinking),
        ("Assistant ", agents_cfg.assistant),
        ("Review    ", agents_cfg.review),
        ("Falsifier ", agents_cfg.falsifier),
        ("CLI       ", agents_cfg.cli),
    ]:
        name = acfg.name or shared.name
        model = acfg.model or shared.model or DEFAULT_MODELS.get(name, "")
        print(f"  {role}  {name} / {model}")
    print(f"{'=' * 60}\n")

    result = await coordinator.run()

    print(f"\n{'=' * 60}")
    if result.success:
        suffix = " (Phase 1 only)" if result.skipped_lean else ""
        print(f"SUCCESS{suffix} after {result.total_roadmaps} roadmap(s)")
        print(f"Run directory: {result.run_dir}")
    else:
        print(f"FAILED after {result.total_roadmaps} roadmap(s)")
        if result.run_dir:
            print(f"Run directory: {result.run_dir}")
    print(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Math Agent -- proof search with Lean 4 verification",
    )
    parser.add_argument("--config", type=Path, default=None, help="Path to config TOML file")
    parser.add_argument("--problem", type=str, default=None, help="Problem ID to solve")
    parser.add_argument("--provider", type=str, default=None, help="LLM provider (shared)")
    parser.add_argument("--model", type=str, default=None, help="Model name (shared)")
    parser.add_argument("--skip-lean", action="store_true", default=False, help="Skip Phase 2")
    parser.add_argument("--resume", type=str, default=None, help="Resume from a previous run dir (timestamp or full path)")
    parser.add_argument("--web", action="store_true", default=False, help="Launch web UI")
    parser.add_argument("--eval", action="store_true", default=False, help="Run eval harness")
    parser.add_argument("--eval-suite", type=str, default=None, help="Eval suite name")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.web:
        from math_agent.webapp import main as web_main
        web_main()
        return

    if args.eval:
        from math_agent.eval.harness import main as eval_main
        # Forward relevant args
        import sys as _sys
        eval_argv = []
        if args.config:
            eval_argv.extend(["--config", str(args.config)])
        if args.eval_suite:
            eval_argv.extend(["--suite", args.eval_suite])
        if args.skip_lean:
            eval_argv.append("--skip-lean")
        _sys.argv = ["math_agent.eval.harness"] + eval_argv
        eval_main()
        return

    config = load_config(args.config)

    # --- Resume mode ---
    resume_from: Path | None = None
    if args.resume:
        resume_path = Path(args.resume)
        # If it's just a timestamp (directory name), resolve relative to runs_dir
        if not resume_path.is_absolute() and not resume_path.is_dir():
            resume_path = config.runs_dir / args.resume
        if not resume_path.is_dir():
            print(f"Error: run directory not found: {resume_path}")
            return
        resume_from = resume_path

        # Load problem from previous run's summary
        summary_path = resume_from / "summary.json"
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                prev_pid = summary.get("problem_id", "")
                prev_question = summary.get("problem", "")
                prev_roadmaps = summary.get("total_roadmaps", 0)
                prev_success = summary.get("success", False)
                print(f"\nResuming from: {resume_from.name}")
                print(f"  Previous problem: {prev_pid}")
                print(f"  Previous status:  {'SUCCESS' if prev_success else 'INCOMPLETE'}")
                print(f"  Roadmaps tried:   {prev_roadmaps}")
            except (json.JSONDecodeError, OSError):
                prev_pid = ""
                prev_question = ""
        else:
            prev_pid = ""
            prev_question = ""

        # Determine problem
        if args.problem:
            problem = load_problem(args.problem)
        elif prev_pid and prev_pid != "custom":
            try:
                problem = load_problem(prev_pid)
            except KeyError:
                if prev_question:
                    problem = ProblemSpec(
                        problem_id=prev_pid,
                        question=prev_question,
                        domain="general",
                        difficulty_level=3,
                        difficulty_label="unknown",
                    )
                else:
                    print("Error: Cannot determine problem. Use --problem to specify.")
                    return
        elif prev_question:
            problem = ProblemSpec(
                problem_id=prev_pid or "custom",
                question=prev_question,
                domain="general",
                difficulty_level=3,
                difficulty_label="custom",
            )
        else:
            print("Error: Cannot determine problem from previous run. Use --problem to specify.")
            return

        # Apply provider overrides
        from dataclasses import replace
        provider_name = args.provider or config.provider.name
        model = args.model or config.provider.model or DEFAULT_MODELS.get(provider_name, "")
        api_key = os.environ.get(API_KEY_ENVS.get(provider_name, ""), "")
        new_provider = replace(config.provider, name=provider_name, model=model, api_key=api_key)
        config = replace(config, provider=new_provider)
        if args.skip_lean:
            config = replace(config, skip_lean=True)

    elif args.problem:
        # Non-interactive mode
        problem = load_problem(args.problem)
        provider_name = args.provider or config.provider.name
        model = args.model or config.provider.model or DEFAULT_MODELS.get(provider_name, "")
        api_key = os.environ.get(API_KEY_ENVS.get(provider_name, ""), "")

        # Override shared provider from CLI args
        from dataclasses import replace
        new_provider = replace(config.provider, name=provider_name, model=model, api_key=api_key)
        config = replace(config, provider=new_provider)
        if args.skip_lean:
            config = replace(config, skip_lean=True)
    else:
        # Interactive mode
        shared, agents, api_keys = select_providers()

        # In interactive mode, offer resume option
        if _offer_resume(config.runs_dir):
            resume_from, prev_problem = _interactive_resume(config.runs_dir)
            if resume_from:
                problem = prev_problem or select_problem()
            else:
                problem = select_problem()
        else:
            problem = select_problem()

        skip_lean = config.skip_lean or ask_skip_lean()

        # Inject API keys into providers
        from dataclasses import replace
        shared_key = api_keys.get(shared.name, "")
        shared = replace(shared, api_key=shared_key)

        def _inject_key(ap: AgentProvider) -> AgentProvider:
            if ap.name:
                return replace(ap, api_key=api_keys.get(ap.name, ""))
            return ap

        agents = replace(
            agents,
            thinking=_inject_key(agents.thinking),
            assistant=_inject_key(agents.assistant),
            review=_inject_key(agents.review),
            cli=_inject_key(agents.cli),
            falsifier=_inject_key(agents.falsifier),
        )

        config = replace(config, provider=shared, agents=agents, skip_lean=skip_lean)

    asyncio.run(run_agent(config, problem, resume_from=resume_from))


if __name__ == "__main__":
    main()
