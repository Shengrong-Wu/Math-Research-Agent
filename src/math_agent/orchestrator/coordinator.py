"""Top-level coordinator: Phase 1 -> Phase 2, with feedback loop."""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from math_agent.config import (
    AppConfig,
    AgentProvider,
    ProviderConfig,
    resolve_agent_provider,
    API_KEY_ENVS,
)
from math_agent.agents.thinking import ThinkingAgent
from math_agent.agents.assistant import AssistantAgent
from math_agent.agents.cli_agent import CLIAgent
from math_agent.agents.falsifier import FalsifierAgent
from math_agent.documents.memo import Memo
from math_agent.documents.notes import Notes
from math_agent.lean.compiler import LeanCompiler
from math_agent.lean.project import LeanProject
from math_agent.llm.base import BaseLLMClient
from math_agent.orchestrator.phase1 import (
    Phase1Runner,
    Phase1Result,
    ThinkingEvent,
)
from math_agent.orchestrator.phase2 import (
    Phase2Runner,
    Phase2Result,
    Phase2Event,
)
from math_agent.problem.spec import ProblemSpec

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client factory (same provider dispatch, but called per-agent)
# ---------------------------------------------------------------------------

def _create_client(
    provider: str,
    model: str,
    temperature: float = 0.7,
    api_key: str = "",
) -> BaseLLMClient:
    """Instantiate the LLM client for *provider*."""
    if not api_key:
        env_key = API_KEY_ENVS.get(provider, "")
        api_key = os.environ.get(env_key, "")

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


def _client_for_agent(
    agent_cfg: AgentProvider,
    shared: ProviderConfig,
    fallback_client: BaseLLMClient | None = None,
) -> BaseLLMClient:
    """Return an LLM client for a specific agent.

    If the agent has its own provider/model override, build a new client.
    Otherwise reuse *fallback_client* (the shared default).
    """
    if agent_cfg.name:
        # Agent has an explicit provider override -> create dedicated client
        name, model, temp = resolve_agent_provider(agent_cfg, shared)
        api_key = agent_cfg.api_key
        return _create_client(name, model, temp, api_key)

    if fallback_client is not None:
        return fallback_client

    # Build from shared config
    name, model, temp = resolve_agent_provider(agent_cfg, shared)
    return _create_client(name, model, temp, shared.api_key)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    success: bool
    phase1: Phase1Result | None = None
    phase2: Phase2Result | None = None
    run_dir: Path | None = None
    total_roadmaps: int = 0
    skipped_lean: bool = False
    events: list[ThinkingEvent | Phase2Event] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

class Coordinator:
    """Top-level orchestrator: Phase 1 -> Phase 2 with feedback.

    Supports per-agent provider/model configuration:

    * If ``config.agents.thinking`` has a non-empty ``name``, the Thinking
      Agent gets its own LLM client with that provider+model.
    * Otherwise it falls back to the shared ``config.provider``.
    * Same for assistant, review, and cli agents.
    """

    def __init__(
        self,
        config: AppConfig,
        client: BaseLLMClient | None = None,
        problem: ProblemSpec | None = None,
        resume_from: Path | None = None,
    ):
        self.config = config
        self._default_client = client
        self.problem = problem
        self.resume_from = resume_from
        self._callbacks: list = []

    # -- convenience for backwards compat (single-client mode) --
    @classmethod
    def from_single_client(
        cls,
        config: AppConfig,
        client: BaseLLMClient,
        problem: ProblemSpec,
    ) -> Coordinator:
        return cls(config, client, problem)

    def on_event(self, callback) -> None:
        """Register a callback for real-time events."""
        self._callbacks.append(callback)

    def _notify(self, event: ThinkingEvent | Phase2Event) -> None:
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Build per-agent clients
    # ------------------------------------------------------------------

    def _build_clients(self) -> dict[str, BaseLLMClient]:
        """Return a dict mapping agent role -> LLM client."""
        shared = self.config.provider
        agents = self.config.agents
        default = self._default_client

        return {
            "thinking": _client_for_agent(agents.thinking, shared, default),
            "assistant": _client_for_agent(agents.assistant, shared, default),
            "review": _client_for_agent(agents.review, shared, default),
            "cli": _client_for_agent(agents.cli, shared, default),
            "falsifier": _client_for_agent(agents.falsifier, shared, default),
        }

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    async def run(self) -> RunResult:
        """Run the full pipeline: Phase 1 -> Phase 2 with feedback loop."""
        assert self.problem is not None, "Coordinator requires a problem."

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = self.config.runs_dir / timestamp
        run_dir.mkdir(parents=True, exist_ok=True)

        # --- Resume: copy state from a previous run ---
        if self.resume_from is not None:
            prev = Path(self.resume_from)
            if not prev.is_dir():
                raise FileNotFoundError(
                    f"Cannot resume: {prev} is not a directory."
                )
            for fname in ("MEMO.json", "MEMO.md", "NOTES.md"):
                src = prev / fname
                if src.exists():
                    shutil.copy2(src, run_dir / fname)
                    logger.info("Resumed %s from %s", fname, prev.name)

        memo = Memo(run_dir / "MEMO.md")
        notes = Notes(run_dir / "NOTES.md")

        # Write a preliminary summary so crashed runs can still be resumed
        preliminary_summary = {
            "success": False,
            "phase": "started",
            "problem_id": self.problem.problem_id,
            "problem": self.problem.question,
            "total_roadmaps": 0,
            "timestamp": timestamp,
            "resumed_from": self.resume_from.name if self.resume_from else None,
        }
        (run_dir / "summary.json").write_text(
            json.dumps(preliminary_summary, indent=2)
        )

        clients = self._build_clients()

        thinking = ThinkingAgent(clients["thinking"], hyper=self.config.hyper)
        assistant = AssistantAgent(clients["assistant"])
        falsifier = FalsifierAgent(clients["falsifier"])

        # Log which provider each agent is using
        for role, c in clients.items():
            logger.info("Agent %-10s -> %s / %s", role, type(c).__name__, c.model)

        max_phase1_retries = 3
        all_events: list[ThinkingEvent | Phase2Event] = []
        total_roadmaps = 0

        for cycle in range(max_phase1_retries):
            logger.info("=== Cycle %d: Phase 1 ===", cycle + 1)

            # --- Phase 1 ---
            phase1 = Phase1Runner(
                thinking=thinking,
                assistant=assistant,
                memo=memo,
                notes=notes,
                hyper=self.config.hyper,
                problem_question=self.problem.question,
                falsifier=falsifier,
            )

            original_emit = phase1._emit
            def emit_with_notify(event, _orig=original_emit):
                _orig(event)
                self._notify(event)
            phase1._emit = emit_with_notify

            result1 = await phase1.run()
            all_events.extend(result1.events)
            total_roadmaps += result1.roadmaps_attempted

            if not result1.success:
                logger.warning(
                    "Phase 1 failed after %d roadmaps.",
                    result1.roadmaps_attempted,
                )
                continue

            # --- Skip Lean? ---
            if self.config.skip_lean:
                logger.info("skip_lean=true -- stopping after Phase 1.")

                summary = {
                    "success": True,
                    "phase": "phase1_only",
                    "problem_id": self.problem.problem_id,
                    "problem": self.problem.question,
                    "cycles": cycle + 1,
                    "total_roadmaps": total_roadmaps,
                    "skip_lean": True,
                    "timestamp": timestamp,
                    "resumed_from": self.resume_from.name if self.resume_from else None,
                }
                (run_dir / "summary.json").write_text(
                    json.dumps(summary, indent=2)
                )

                return RunResult(
                    success=True,
                    phase1=result1,
                    phase2=None,
                    run_dir=run_dir,
                    total_roadmaps=total_roadmaps,
                    skipped_lean=True,
                    events=all_events,
                )

            # --- Phase 2 ---
            logger.info("=== Cycle %d: Phase 2 ===", cycle + 1)

            lean_project = LeanProject(
                workspace=run_dir / "lean-workspace",
                toolchain=self.config.lean.toolchain,
                use_mathlib=self.config.lean.mathlib,
            )
            lean_project.init()
            compiler = LeanCompiler(lean_project.workspace)

            # Download Mathlib cache (uses local ~/.cache/mathlib if available)
            if self.config.lean.mathlib:
                import subprocess
                logger.info("Resolving Lean dependencies (lake update)…")
                subprocess.run(
                    [compiler._lake, "update"],
                    cwd=str(lean_project.workspace),
                    env=compiler._env,
                    capture_output=True,
                    timeout=300,
                )
                await compiler.cache_get()

            cli_agent = CLIAgent(clients["cli"])

            phase2 = Phase2Runner(
                cli_agent=cli_agent,
                lean_project=lean_project,
                compiler=compiler,
                runs_dir=run_dir,
                proof=result1.complete_proof,
            )

            original_emit2 = phase2._emit
            def emit2_with_notify(event, _orig=original_emit2):
                _orig(event)
                self._notify(event)
            phase2._emit = emit2_with_notify

            result2 = await phase2.run()
            all_events.extend(result2.events)

            if result2.success:
                summary = {
                    "success": True,
                    "problem_id": self.problem.problem_id,
                    "problem": self.problem.question,
                    "cycles": cycle + 1,
                    "total_roadmaps": total_roadmaps,
                    "modules_completed": result2.modules_completed,
                    "external_claims": result2.external_claims,
                    "timestamp": timestamp,
                    "resumed_from": self.resume_from.name if self.resume_from else None,
                }
                (run_dir / "summary.json").write_text(
                    json.dumps(summary, indent=2)
                )

                return RunResult(
                    success=True,
                    phase1=result1,
                    phase2=result2,
                    run_dir=run_dir,
                    total_roadmaps=total_roadmaps,
                    events=all_events,
                )

            if result2.structural_issue:
                logger.warning(
                    "Phase 2 structural issue: %s",
                    result2.structural_issue,
                )
                memo_state = memo.load()
                achieved = [
                    p.prop_id for p in memo_state.proved_propositions
                ]
                memo.archive_roadmap(
                    f"Roadmap (Lean failed, cycle {cycle + 1})",
                    result1.complete_proof[:200],
                    result2.structural_issue,
                    achieved,
                    f"Lean formalization failed: {result2.structural_issue}",
                )
                continue

            logger.warning(
                "Phase 2 failed: %d modules incomplete",
                len(result2.modules_failed),
            )

        # All cycles exhausted
        summary = {
            "success": False,
            "problem_id": self.problem.problem_id,
            "problem": self.problem.question,
            "total_roadmaps": total_roadmaps,
            "timestamp": timestamp,
            "resumed_from": self.resume_from.name if self.resume_from else None,
        }
        (run_dir / "summary.json").write_text(
            json.dumps(summary, indent=2)
        )

        return RunResult(
            success=False,
            run_dir=run_dir,
            total_roadmaps=total_roadmaps,
            events=all_events,
        )
