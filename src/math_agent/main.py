"""CLI entry point with interactive wizard for the Math Agent."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import logging
from pathlib import Path

from math_agent.config import load_config, AppConfig
from math_agent.problem.spec import (
    load_problem,
    list_problems,
    list_suites,
    load_suite,
    ProblemSpec,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Interactive selection helpers
# ---------------------------------------------------------------------------

def select_provider() -> tuple[str, str, str]:
    """Interactive provider selection. Returns (provider_name, model, api_key)."""
    providers = {
        "1": ("anthropic", "claude-opus-4-0626", "ANTHROPIC_API_KEY"),
        "2": ("openai", "o3", "OPENAI_API_KEY"),
        "3": ("deepseek", "deepseek-reasoner", "DEEPSEEK_API_KEY"),
        "4": ("gemini", "gemini-2.5-pro", "GEMINI_API_KEY"),
    }
    print("\nSelect provider:")
    print("  1. Anthropic (Claude Opus 4)")
    print("  2. OpenAI (o3)")
    print("  3. DeepSeek (Reasoner)")
    print("  4. Google (Gemini 2.5 Pro)")
    choice = input("\nChoice [1]: ").strip() or "1"

    if choice not in providers:
        print(f"Invalid choice: {choice}. Using Anthropic.")
        choice = "1"

    name, default_model, env_key = providers[choice]

    model = input(f"Model [{default_model}]: ").strip() or default_model

    api_key = os.environ.get(env_key, "")
    if not api_key:
        api_key = input(f"API key ({env_key}): ").strip()

    return name, model, api_key


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
        idx = input(f"\nProblem number [1]: ").strip() or "1"
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
        idx = input(f"\nSuite number [1]: ").strip() or "1"
        suite_names = list(suites.keys())
        try:
            suite_name = suite_names[int(idx) - 1]
        except (IndexError, ValueError):
            suite_name = suite_names[0]
        suite_problems = load_suite(suite_name)
        print(f"\nRunning suite '{suite_name}' with {len(suite_problems)} problems.")
        # For now, run the first problem. Suite mode can be expanded later.
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


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def create_client(provider: str, model: str, api_key: str, temperature: float = 0.7):
    """Create the appropriate LLM client for *provider*."""
    if provider == "anthropic":
        from math_agent.llm.anthropic_client import AnthropicClient

        return AnthropicClient(model=model, api_key=api_key, temperature=temperature)
    elif provider == "openai":
        from math_agent.llm.openai_client import OpenAIClient

        return OpenAIClient(model=model, api_key=api_key, temperature=temperature)
    elif provider == "deepseek":
        from math_agent.llm.deepseek_client import DeepSeekClient

        return DeepSeekClient(model=model, api_key=api_key, temperature=temperature)
    elif provider == "gemini":
        from math_agent.llm.gemini_client import GeminiClient

        return GeminiClient(model=model, api_key=api_key, temperature=temperature)
    else:
        raise ValueError(f"Unknown provider: {provider}")


# ---------------------------------------------------------------------------
# Agent runner
# ---------------------------------------------------------------------------

async def run_agent(
    config: AppConfig,
    provider: str,
    model: str,
    api_key: str,
    problem: ProblemSpec,
) -> None:
    """Run the full agent pipeline for a single problem."""
    from math_agent.orchestrator.coordinator import Coordinator

    client = create_client(provider, model, api_key, config.provider.temperature)
    coordinator = Coordinator(config, client, problem)

    # Print events to the console as they arrive.
    def on_event(event):
        prefix = (
            getattr(event, "module_name", "")
            or f"step {getattr(event, 'step_index', '?')}"
        )
        print(f"  [{event.event_type}] {prefix}: {event.content[:200]}")

    coordinator.on_event(on_event)

    print(f"\n{'=' * 60}")
    print(f"Problem: {problem.question[:80]}...")
    print(f"Domain: {problem.domain} | Difficulty: {problem.difficulty_label}")
    print(f"Provider: {provider} / {model}")
    print(f"{'=' * 60}\n")

    result = await coordinator.run()

    print(f"\n{'=' * 60}")
    if result.success:
        print(f"SUCCESS after {result.total_roadmaps} roadmap(s)")
        print(f"Run directory: {result.run_dir}")
    else:
        print(f"FAILED after {result.total_roadmaps} roadmap(s)")
        if result.run_dir:
            print(f"Run directory: {result.run_dir}")
    print(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-opus-4-0626",
    "openai": "o3",
    "deepseek": "deepseek-reasoner",
    "gemini": "gemini-2.5-pro",
}

_API_KEY_ENVS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Math Agent -- proof search with Lean 4 verification",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config TOML file",
    )
    parser.add_argument(
        "--problem",
        type=str,
        default=None,
        help="Problem ID to solve (skips interactive selection)",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="LLM provider name (anthropic, openai, deepseek, gemini)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model name override",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        default=False,
        help="Launch the web UI instead of the CLI wizard",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # If --web is given, delegate to the webapp.
    if args.web:
        from math_agent.webapp import main as web_main

        web_main()
        return

    config = load_config(args.config)

    if args.problem:
        problem = load_problem(args.problem)
        provider = args.provider or config.provider.name
        model = args.model or config.provider.model or _DEFAULT_MODELS.get(provider, "")
        api_key = os.environ.get(_API_KEY_ENVS.get(provider, ""), "")
    else:
        provider, model, api_key = select_provider()
        problem = select_problem()

    asyncio.run(run_agent(config, provider, model, api_key, problem))


if __name__ == "__main__":
    main()
