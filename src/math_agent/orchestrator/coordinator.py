"""Top-level coordinator: Phase 1 -> Phase 2, with feedback loop."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from math_agent.config import AppConfig
from math_agent.agents.thinking import ThinkingAgent
from math_agent.agents.assistant import AssistantAgent
from math_agent.agents.cli_agent import CLIAgent
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


@dataclass
class RunResult:
    success: bool
    phase1: Phase1Result | None = None
    phase2: Phase2Result | None = None
    run_dir: Path | None = None
    total_roadmaps: int = 0
    events: list[ThinkingEvent | Phase2Event] = field(default_factory=list)


class Coordinator:
    """Top-level orchestrator: Phase 1 -> Phase 2 with feedback."""

    def __init__(
        self,
        config: AppConfig,
        client: BaseLLMClient,
        problem: ProblemSpec,
    ):
        self.config = config
        self.client = client
        self.problem = problem
        self._callbacks: list = []  # event callbacks for web UI

    def on_event(self, callback) -> None:
        """Register a callback for real-time events."""
        self._callbacks.append(callback)

    def _notify(self, event: ThinkingEvent | Phase2Event) -> None:
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception:
                pass

    async def run(self) -> RunResult:
        """Run the full pipeline: Phase 1 -> Phase 2 with feedback loop."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = self.config.runs_dir / timestamp
        run_dir.mkdir(parents=True, exist_ok=True)

        memo = Memo(run_dir / "MEMO.md")
        notes = Notes(run_dir / "NOTES.md")

        thinking = ThinkingAgent(self.client)
        assistant = AssistantAgent(self.client)

        max_phase1_retries = 3  # Phase 2 can send us back
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
            )

            # Wire event callbacks
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

            # --- Phase 2 ---
            logger.info("=== Cycle %d: Phase 2 ===", cycle + 1)

            lean_project = LeanProject(
                workspace=run_dir / "lean-workspace",
                toolchain=self.config.lean.toolchain,
                use_mathlib=self.config.lean.mathlib,
            )
            compiler = LeanCompiler(lean_project.workspace)
            cli_agent = CLIAgent(self.client)

            phase2 = Phase2Runner(
                cli_agent=cli_agent,
                lean_project=lean_project,
                compiler=compiler,
                runs_dir=run_dir,
                proof=result1.complete_proof,
            )

            # Wire events
            original_emit2 = phase2._emit

            def emit2_with_notify(event, _orig=original_emit2):
                _orig(event)
                self._notify(event)

            phase2._emit = emit2_with_notify

            result2 = await phase2.run()
            all_events.extend(result2.events)

            if result2.success:
                # Write summary
                summary = {
                    "success": True,
                    "problem_id": self.problem.problem_id,
                    "problem": self.problem.question,
                    "cycles": cycle + 1,
                    "total_roadmaps": total_roadmaps,
                    "modules_completed": result2.modules_completed,
                    "external_claims": result2.external_claims,
                    "timestamp": timestamp,
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
                # Feed structural issue back to Phase 1 via MEMO
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
                # Loop back to Phase 1
                continue

            # Phase 2 failed without structural issue (just couldn't formalize)
            logger.warning(
                "Phase 2 failed: %d modules incomplete",
                len(result2.modules_failed),
            )

        # Write failure summary
        summary = {
            "success": False,
            "problem_id": self.problem.problem_id,
            "problem": self.problem.question,
            "total_roadmaps": total_roadmaps,
            "timestamp": timestamp,
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
