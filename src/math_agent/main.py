"""CLI entry point with interactive wizard for the Math Agent."""

from __future__ import annotations

import argparse
import asyncio
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

        # Use the thinking agent's provider as the shared default
        shared = ProviderConfig(name=t_name, model=t_model, temperature=0.7)
        agents = AgentConfigs(
            thinking=AgentProvider(name=t_name, model=t_model),
            assistant=AgentProvider(name=a_name, model=a_model),
            review=AgentProvider(name=r_name, model=r_model),
            cli=AgentProvider(name=c_name, model=c_model),
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


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run_agent(config: AppConfig, problem: ProblemSpec) -> None:
    """Run the full agent pipeline for a single problem."""
    from math_agent.orchestrator.coordinator import Coordinator

    coordinator = Coordinator(config=config, problem=problem)

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
    print(f"Problem: {problem.question[:80]}...")
    print(f"Domain:  {problem.domain} | Difficulty: {problem.difficulty_label}")
    print(f"Phase 2: {'SKIP (math proof only)' if config.skip_lean else 'Lean 4 formalization'}")
    print(f"{'─' * 60}")
    for role, acfg in [
        ("Thinking ", agents_cfg.thinking),
        ("Assistant", agents_cfg.assistant),
        ("Review   ", agents_cfg.review),
        ("CLI      ", agents_cfg.cli),
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
    parser.add_argument("--web", action="store_true", default=False, help="Launch web UI")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.web:
        from math_agent.webapp import main as web_main
        web_main()
        return

    config = load_config(args.config)

    if args.problem:
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
        )

        config = replace(config, provider=shared, agents=agents, skip_lean=skip_lean)

    asyncio.run(run_agent(config, problem))


if __name__ == "__main__":
    main()
