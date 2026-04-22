"""Top-level coordinator for Math Agent."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from math_agent.agents.assistant import AssistantAgent
from math_agent.agents.falsifier import FalsifierAgent
from math_agent.agents.formalizer import FormalizerAgent
from math_agent.agents.thinking import ThinkingAgent
from math_agent.config import AppConfig
from math_agent.documents.memo import Memo
from math_agent.documents.notes import Notes
from math_agent.orchestrator.phase1 import Phase1Result, Phase1Runner, ThinkingEvent
from math_agent.problem.spec import ProblemSpec
from math_agent.runtime import build_role_sessions

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    success: bool
    phase1: Phase1Result | None = None
    run_dir: Path | None = None
    total_roadmaps: int = 0
    events: list[ThinkingEvent] = field(default_factory=list)
    crash_free: bool = True
    error_message: str = ""
    prompt_telemetry: dict[str, object] = field(default_factory=dict)


class Coordinator:
    """Top-level orchestrator for the v3-style Phase 1 pipeline."""

    def __init__(
        self,
        config: AppConfig,
        problem: ProblemSpec | None = None,
        resume_from: Path | None = None,
    ) -> None:
        self.config = config
        self.problem = problem
        self.resume_from = resume_from
        self._callbacks: list = []

    def on_event(self, callback) -> None:
        self._callbacks.append(callback)

    def _notify(self, event: ThinkingEvent) -> None:
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception:
                logger.debug("Event callback failed.", exc_info=True)

    @staticmethod
    def _phase1_signal_summary(result: Phase1Result) -> dict[str, object]:
        signals = {
            "phase1_success": result.success,
            "review_passed": False,
            "falsifier_passed": False,
        }
        saw_review = False
        saw_falsifier = False
        for event in result.events:
            if event.event_type == "review_result":
                saw_review = True
                if not bool(event.metadata.get("has_gaps", True)):
                    signals["review_passed"] = True
            elif event.event_type == "falsifier_result":
                saw_falsifier = True
                if str(event.metadata.get("verdict", "")).upper() != "FAIL":
                    signals["falsifier_passed"] = True
        if result.success:
            if not saw_review:
                signals["review_passed"] = True
            if not saw_falsifier:
                signals["falsifier_passed"] = True
        return signals

    @staticmethod
    def _collect_prompt_telemetry(runtime_root: Path) -> dict[str, object]:
        summary = {
            "calls": 0,
            "max_prompt_chars": 0,
            "max_transcript_chars": 0,
            "max_prompt_tokens_estimate": 0,
            "near_limit_calls": 0,
            "used_native_resume_calls": 0,
            "retried_calls": 0,
            "max_retry_count": 0,
            "by_callsite": {},
        }
        if not runtime_root.exists():
            return summary

        by_callsite: dict[str, dict[str, int]] = {}
        for result_path in runtime_root.glob("*/invocations/*/result.json"):
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            meta = payload.get("metadata", {})
            summary["calls"] += 1
            prompt_chars = int(meta.get("prompt_chars", 0))
            transcript_chars = int(meta.get("transcript_chars", 0))
            prompt_tokens = int(meta.get("prompt_token_estimate", 0))
            retry_count = int(meta.get("retry_count", 0))
            summary["max_prompt_chars"] = max(summary["max_prompt_chars"], prompt_chars)
            summary["max_transcript_chars"] = max(summary["max_transcript_chars"], transcript_chars)
            summary["max_prompt_tokens_estimate"] = max(
                summary["max_prompt_tokens_estimate"],
                prompt_tokens,
            )
            if bool(meta.get("near_limit", False)):
                summary["near_limit_calls"] += 1
            if bool(payload.get("used_native_resume", False)):
                summary["used_native_resume_calls"] += 1
            if retry_count:
                summary["retried_calls"] += 1
            summary["max_retry_count"] = max(summary["max_retry_count"], retry_count)
            callsite = str(meta.get("callsite", "unspecified"))
            slot = by_callsite.setdefault(
                callsite,
                {
                    "calls": 0,
                    "max_prompt_chars": 0,
                    "max_prompt_tokens_estimate": 0,
                    "near_limit_calls": 0,
                    "retried_calls": 0,
                    "assembly_profiles": {},
                },
            )
            slot["calls"] += 1
            slot["max_prompt_chars"] = max(slot["max_prompt_chars"], prompt_chars)
            slot["max_prompt_tokens_estimate"] = max(slot["max_prompt_tokens_estimate"], prompt_tokens)
            if bool(meta.get("near_limit", False)):
                slot["near_limit_calls"] += 1
            if retry_count:
                slot["retried_calls"] += 1
            profile = str(meta.get("assembly_profile", "")).strip()
            if profile:
                profiles = slot["assembly_profiles"]
                profiles[profile] = int(profiles.get(profile, 0)) + 1
        summary["by_callsite"] = by_callsite
        return summary

    def _lean_bootstrap_stamp(self) -> dict[str, object]:
        return {
            "toolchain": self.config.lean.toolchain,
            "mathlib": self.config.lean.mathlib,
        }

    async def _prepare_toolplane(self):
        if self.config.lean_mode != "check":
            return None

        from math_agent.lean.compiler import LeanCompiler
        from math_agent.lean.project import LeanProject
        from math_agent.lean.toolplane import LeanToolplane

        if not LeanToolplane.is_available():
            logger.warning("Lean verification requested, but lake/elan is unavailable. Continuing without Lean.")
            return None

        workspace = self.config.lean.workspace
        stamp_path = workspace / ".math-agent-bootstrap.json"
        desired_stamp = self._lean_bootstrap_stamp()

        def workspace_has_required_files() -> bool:
            if not (workspace / "lean-toolchain").exists():
                return False
            if not (workspace / "lakefile.toml").exists() and not (workspace / "lakefile.lean").exists():
                return False
            if self.config.lean.mathlib and not (workspace / ".lake" / "packages" / "mathlib").exists():
                return False
            return True

        def workspace_matches_configuration() -> bool:
            if not workspace_has_required_files():
                return False
            try:
                toolchain = (workspace / "lean-toolchain").read_text(encoding="utf-8").strip()
            except OSError:
                return False
            return toolchain == self.config.lean.toolchain

        def workspace_matches_stamp() -> bool:
            if not stamp_path.exists():
                return False
            try:
                current = json.loads(stamp_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return False
            if current != desired_stamp:
                return False
            return workspace_matches_configuration()

        try:
            if workspace_matches_stamp() or workspace_matches_configuration():
                project = LeanProject(
                    workspace=workspace,
                    toolchain=self.config.lean.toolchain,
                    use_mathlib=self.config.lean.mathlib,
                )
                project.init()
                workspace.mkdir(parents=True, exist_ok=True)
                stamp_path.write_text(json.dumps(desired_stamp, indent=2), encoding="utf-8")
                compiler = LeanCompiler(workspace)
                return LeanToolplane(compiler, workspace)

            if workspace.exists():
                shutil.rmtree(workspace)

            project = LeanProject(
                workspace=workspace,
                toolchain=self.config.lean.toolchain,
                use_mathlib=self.config.lean.mathlib,
            )
            project.init()
            compiler = LeanCompiler(workspace)

            if self.config.lean.mathlib:
                logger.info("Bootstrapping shared Lean workspace in %s", workspace)
                update = subprocess.run(
                    [compiler._lake, "update"],
                    cwd=str(workspace),
                    env=compiler._env,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if update.returncode != 0:
                    logger.warning("Lean workspace bootstrap failed during lake update: %s", update.stderr[:500])
                    return None
                if not await compiler.cache_get():
                    logger.warning("Lean workspace bootstrap failed during lake exe cache get.")
                    return None

            workspace.mkdir(parents=True, exist_ok=True)
            stamp_path.write_text(json.dumps(desired_stamp, indent=2), encoding="utf-8")
            return LeanToolplane(compiler, workspace)
        except Exception as exc:
            logger.warning("Failed to prepare shared Lean workspace: %s", exc)
            return None

    async def run(self) -> RunResult:
        assert self.problem is not None, "Coordinator requires a problem."

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = self.config.runs_dir / timestamp
        run_dir.mkdir(parents=True, exist_ok=True)

        if self.resume_from is not None:
            prev = Path(self.resume_from)
            if not prev.is_dir():
                raise FileNotFoundError(f"Cannot resume: {prev} is not a directory.")
            for fname in ("MEMO.json", "MEMO.md", "NOTES.md"):
                src = prev / fname
                if src.exists():
                    shutil.copy2(src, run_dir / fname)
                    logger.info("Resumed %s from %s", fname, prev.name)

        runtime_root = run_dir / "agent_runtime"
        runtime_root.mkdir(exist_ok=True)

        memo = Memo(run_dir / "MEMO.md")
        notes = Notes(run_dir / "NOTES.md")
        preliminary_summary = {
            "success": False,
            "phase": "started",
            "problem_id": self.problem.problem_id,
            "problem": self.problem.question,
            "roadmaps_attempted": 0,
            "total_roadmaps": 0,
            "lean_mode": self.config.lean_mode,
            "runtime": {
                "backend": self.config.runtime.backend,
                "model": self.config.runtime.model,
            },
            "timestamp": timestamp,
            "resumed_from": self.resume_from.name if self.resume_from else None,
        }
        (run_dir / "summary.json").write_text(json.dumps(preliminary_summary, indent=2))

        toolplane = await self._prepare_toolplane()
        sessions = build_role_sessions(
            self.config,
            runtime_root,
            default_workspace=run_dir,
        )

        thinking = ThinkingAgent(sessions["thinking"], hyper=self.config.hyper)
        formalizer = FormalizerAgent(sessions["formalizer"])
        assistant = AssistantAgent(sessions["assistant"])
        falsifier = FalsifierAgent(sessions["falsifier"])

        phase1 = Phase1Runner(
            thinking=thinking,
            formalizer=formalizer,
            assistant=assistant,
            memo=memo,
            notes=notes,
            hyper=self.config.hyper,
            prompt_budgets=self.config.prompt_budgets,
            problem_question=self.problem.question,
            falsifier=falsifier,
            review_runtime=sessions["review"],
            toolplane=toolplane,
        )

        original_emit = phase1._emit

        def emit_with_notify(event, _orig=original_emit):
            _orig(event)
            self._notify(event)

        phase1._emit = emit_with_notify

        try:
            result = await phase1.run()
            signals = self._phase1_signal_summary(result)
            prompt_telemetry = self._collect_prompt_telemetry(runtime_root)
            summary = {
                "success": result.success,
                "phase": "phase1_only",
                "problem_id": self.problem.problem_id,
                "problem": self.problem.question,
                "roadmaps_attempted": result.roadmaps_attempted,
                "total_roadmaps": result.roadmaps_attempted,
                "phase1_signals": signals,
                "lean_mode": self.config.lean_mode,
                "crash_free": True,
                "prompt_telemetry": prompt_telemetry,
                "runtime": {
                    "backend": self.config.runtime.backend,
                    "model": self.config.runtime.model,
                },
                "timestamp": timestamp,
                "resumed_from": self.resume_from.name if self.resume_from else None,
            }
            (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
            return RunResult(
                success=result.success,
                phase1=result,
                run_dir=run_dir,
                total_roadmaps=result.roadmaps_attempted,
                events=result.events,
                crash_free=True,
                prompt_telemetry=prompt_telemetry,
            )
        except Exception as exc:
            logger.exception("Coordinator run failed.")
            summary = {
                "success": False,
                "phase": "phase1_only",
                "problem_id": self.problem.problem_id,
                "problem": self.problem.question,
                "roadmaps_attempted": 0,
                "total_roadmaps": 0,
                "lean_mode": self.config.lean_mode,
                "crash_free": False,
                "error_message": str(exc),
                "prompt_telemetry": self._collect_prompt_telemetry(runtime_root),
                "timestamp": timestamp,
                "resumed_from": self.resume_from.name if self.resume_from else None,
            }
            (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
            return RunResult(
                success=False,
                phase1=None,
                run_dir=run_dir,
                total_roadmaps=0,
                events=[],
                crash_free=False,
                error_message=str(exc),
                prompt_telemetry=self._collect_prompt_telemetry(runtime_root),
            )
