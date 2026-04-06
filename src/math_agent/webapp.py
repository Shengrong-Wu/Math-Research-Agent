"""FastAPI web server with WebSocket streaming for the Math Agent UI."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from math_agent.config import (
    load_config,
    AppConfig,
    Hyperparameters,
    ProviderConfig,
    AgentConfigs,
    AgentProvider,
    DEFAULT_MODELS,
    API_KEY_ENVS,
)
from math_agent.problem.spec import (
    ProblemSpec,
    list_problems,
    list_suites,
    load_problem,
    load_suite,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Web directory (relative to this file)
# ---------------------------------------------------------------------------

_WEB_DIR = Path(__file__).parent / "web"

# ---------------------------------------------------------------------------
# Known models (hardcoded fallback when API is unavailable)
# ---------------------------------------------------------------------------

KNOWN_MODELS: dict[str, list[str]] = {
    "anthropic": [
        "claude-opus-4-0626",
        "claude-sonnet-4-0626",
        "claude-haiku-4-0626",
    ],
    "openai": [
        "o3",
        "o4-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
    ],
    "deepseek": [
        "deepseek-reasoner",
        "deepseek-chat",
    ],
    "gemini": [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
    ],
}

# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------


@dataclass
class RunState:
    """Global mutable state for the current agent run."""

    running: bool = False
    problem: ProblemSpec | None = None
    provider: str = ""
    model: str = ""
    memo_snapshot: dict[str, Any] = field(default_factory=dict)
    notes_content: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = 0.0


_state = RunState()
_ws_clients: set[WebSocket] = set()


# ---------------------------------------------------------------------------
# Broadcast helpers
# ---------------------------------------------------------------------------


async def _broadcast(message: dict[str, Any]) -> None:
    """Send a JSON message to every connected WebSocket client."""
    payload = json.dumps(message)
    stale: list[WebSocket] = []
    for ws in _ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            stale.append(ws)
    for ws in stale:
        _ws_clients.discard(ws)


async def broadcast_memo_update(memo_dict: dict[str, Any]) -> None:
    """Broadcast a MEMO state update to all clients."""
    _state.memo_snapshot = memo_dict
    await _broadcast({"type": "memo_update", "data": memo_dict})


async def broadcast_thinking(
    event_type: str,
    step: int | str,
    content: str,
    *,
    module_name: str = "",
) -> None:
    """Broadcast a thinking/progress event to all clients."""
    event = {
        "event_type": event_type,
        "step": step,
        "content": content,
        "module_name": module_name,
        "timestamp": time.time(),
    }
    _state.events.append(event)
    await _broadcast({"type": "thinking", "data": event})


# ---------------------------------------------------------------------------
# Model fetching from provider APIs
# ---------------------------------------------------------------------------


async def _fetch_models_from_api(provider: str, api_key: str) -> list[str]:
    """Try to fetch available model IDs from the provider's API."""
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        if provider == "openai":
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            ids = [m["id"] for m in data.get("data", [])]
            # Keep only chat / reasoning models
            prefixes = ("gpt-", "o1", "o3", "o4", "chatgpt")
            ids = [m for m in ids if any(m.startswith(p) for p in prefixes)]
            return sorted(ids)

        elif provider == "gemini":
            resp = await client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            ids = []
            for m in data.get("models", []):
                name = m.get("name", "")
                if name.startswith("models/"):
                    name = name[7:]
                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" in methods:
                    ids.append(name)
            return sorted(ids)

        elif provider == "deepseek":
            resp = await client.get(
                "https://api.deepseek.com/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            return sorted([m["id"] for m in data.get("data", [])])

    # Anthropic and unknown providers: no listing API
    return []


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class ModelListRequest(BaseModel):
    """JSON body for POST /api/models."""

    provider: str = "anthropic"
    api_key: str = ""


class AgentRunConfig(BaseModel):
    """Per-agent provider+model override for web UI."""

    provider: str = ""
    model: str = ""
    api_key: str = ""


class RunRequest(BaseModel):
    """JSON body for POST /api/run."""

    # Shared provider config (used when multi_agent is False)
    provider: str = "anthropic"
    model: str = ""
    api_key: str = ""

    # Multi-agent config
    multi_agent: bool = False
    thinking: Optional[AgentRunConfig] = None
    assistant: Optional[AgentRunConfig] = None
    review: Optional[AgentRunConfig] = None
    cli: Optional[AgentRunConfig] = None

    # Problem
    problem_id: Optional[str] = None
    custom_question: Optional[str] = None
    custom_domain: str = "general"

    # Options
    skip_lean: bool = True

    # Resume from a previous run (timestamp directory name)
    resume_run_id: Optional[str] = None

    # Hyperparameters (optional overrides)
    N: Optional[int] = None
    C: Optional[int] = None
    K: Optional[int] = None


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="Math Agent", version="0.1.0")

# Serve static files (CSS, JS) from the web directory.
app.mount("/static", StaticFiles(directory=str(_WEB_DIR)), name="static")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/")
async def index():
    """Serve the main HTML page."""
    return FileResponse(str(_WEB_DIR / "index.html"))


@app.get("/api/memo")
async def get_memo():
    """Return the current MEMO state as JSON."""
    return JSONResponse(_state.memo_snapshot)


@app.get("/api/notes")
async def get_notes():
    """Return the current NOTES content."""
    return JSONResponse({"content": _state.notes_content})


@app.get("/api/problems")
async def get_problems():
    """Return a list of available built-in problems."""
    problems = []
    for pid in list_problems():
        p = load_problem(pid)
        problems.append(
            {
                "problem_id": p.problem_id,
                "question": p.question,
                "domain": p.domain,
                "difficulty_level": p.difficulty_level,
                "difficulty_label": p.difficulty_label,
            }
        )
    return JSONResponse(problems)


@app.get("/api/suites")
async def get_suites():
    """Return a list of available problem suites."""
    suites_raw = list_suites()
    result = []
    for name, pids in suites_raw.items():
        result.append({"name": name, "problem_ids": pids, "count": len(pids)})
    return JSONResponse(result)


@app.get("/api/status")
async def get_status():
    """Return the current run status."""
    return JSONResponse(
        {
            "running": _state.running,
            "provider": _state.provider,
            "model": _state.model,
            "problem_id": _state.problem.problem_id if _state.problem else None,
            "started_at": _state.started_at,
            "event_count": len(_state.events),
        }
    )


@app.get("/api/runs")
async def get_runs():
    """Return a list of previous runs with metadata for resume.

    Scans the ``runs/`` directory for timestamped subdirectories and
    reads each ``summary.json`` to extract problem info and status.
    Runs are returned in reverse chronological order (newest first).
    """
    base_config = load_config()
    runs_dir = base_config.runs_dir
    if not runs_dir.is_dir():
        return JSONResponse([])

    result: list[dict[str, Any]] = []
    for entry in sorted(runs_dir.iterdir(), reverse=True):
        if not entry.is_dir() or entry.name.startswith("."):
            continue

        run_info: dict[str, Any] = {
            "run_id": entry.name,
            "timestamp": entry.name,
            "has_memo": (entry / "MEMO.json").exists() or (entry / "MEMO.md").exists(),
            "has_notes": (entry / "NOTES.md").exists(),
            "has_summary": (entry / "summary.json").exists(),
        }

        # Read summary if available
        summary_path = entry / "summary.json"
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                run_info["success"] = summary.get("success")
                run_info["problem_id"] = summary.get("problem_id", "")
                run_info["problem"] = summary.get("problem", "")
                run_info["total_roadmaps"] = summary.get("total_roadmaps", 0)
                run_info["skip_lean"] = summary.get("skip_lean", False)
                run_info["phase"] = summary.get("phase", "")
            except (json.JSONDecodeError, OSError):
                pass

        # If no summary, try to infer from MEMO
        if "problem_id" not in run_info:
            memo_path = entry / "MEMO.json"
            if memo_path.exists():
                try:
                    memo_data = json.loads(memo_path.read_text(encoding="utf-8"))
                    n_proved = len(memo_data.get("proved_propositions", []))
                    n_archived = len(memo_data.get("previous_roadmaps", []))
                    run_info["memo_proved"] = n_proved
                    run_info["memo_archived_roadmaps"] = n_archived
                except (json.JSONDecodeError, OSError):
                    pass

        # Only include runs that have at least a MEMO (meaningful state)
        if run_info["has_memo"]:
            result.append(run_info)

    return JSONResponse(result)


@app.get("/api/env-keys")
async def get_env_keys():
    """Check which providers have API keys configured in environment."""
    result = {}
    for provider, env_var in API_KEY_ENVS.items():
        key = os.environ.get(env_var, "")
        result[provider] = {
            "env_var": env_var,
            "configured": bool(key),
            "prefix": (key[:4] + "...") if len(key) > 4 else ("***" if key else ""),
        }
    return JSONResponse(result)


@app.post("/api/models")
async def get_models(req: ModelListRequest):
    """Return available models for a provider.

    Uses hardcoded lists by default, enriches with API-fetched
    models when an API key is available (from request or env).
    """
    models = list(KNOWN_MODELS.get(req.provider, []))

    # Try to enrich with API-fetched models
    api_key = req.api_key
    if not api_key:
        env_var = API_KEY_ENVS.get(req.provider, "")
        api_key = os.environ.get(env_var, "")

    if api_key:
        try:
            fetched = await _fetch_models_from_api(req.provider, api_key)
            if fetched:
                known_set = set(models)
                models = models + [m for m in fetched if m not in known_set]
        except Exception as e:
            logger.warning("Failed to fetch models for %s: %s", req.provider, e)

    return JSONResponse({"provider": req.provider, "models": models})


@app.post("/api/run")
async def start_run(req: RunRequest):
    """Start a new agent run in the background."""
    if _state.running:
        return JSONResponse(
            {"error": "A run is already in progress."},
            status_code=409,
        )

    # --- Resolve resume path ---
    resume_from: Path | None = None
    if req.resume_run_id:
        base_config = load_config()
        resume_from = base_config.runs_dir / req.resume_run_id
        if not resume_from.is_dir():
            return JSONResponse(
                {"error": f"Run directory not found: {req.resume_run_id}"},
                status_code=404,
            )

    # Resolve the problem.
    if req.problem_id:
        try:
            problem = load_problem(req.problem_id)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
    elif req.custom_question:
        problem = ProblemSpec(
            problem_id="custom",
            question=req.custom_question,
            domain=req.custom_domain,
            difficulty_level=3,
            difficulty_label="custom",
        )
    elif resume_from:
        # Auto-resolve problem from the previous run's summary
        summary_path = resume_from / "summary.json"
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
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
                else:
                    return JSONResponse(
                        {"error": "Cannot determine problem from previous run."},
                        status_code=400,
                    )
            except (json.JSONDecodeError, OSError):
                return JSONResponse(
                    {"error": "Cannot read summary.json from previous run."},
                    status_code=400,
                )
        else:
            return JSONResponse(
                {"error": "Previous run has no summary.json. Specify problem_id explicitly."},
                status_code=400,
            )
    else:
        return JSONResponse(
            {"error": "Provide problem_id, custom_question, or resume_run_id."},
            status_code=400,
        )

    model = req.model or DEFAULT_MODELS.get(req.provider, "")

    # Reset state and launch the run.
    _state.running = True
    _state.problem = problem
    _state.provider = req.provider
    _state.model = model
    _state.memo_snapshot = {}
    _state.notes_content = ""
    _state.events = []
    _state.started_at = time.time()

    asyncio.create_task(_execute_run(req, problem, resume_from=resume_from))

    return JSONResponse(
        {
            "status": "started" if not resume_from else "resumed",
            "problem_id": problem.problem_id,
            "provider": req.provider,
            "model": model,
            "resume_from": str(resume_from.name) if resume_from else None,
        }
    )


# ---------------------------------------------------------------------------
# Background execution
# ---------------------------------------------------------------------------


def _build_config(req: RunRequest) -> AppConfig:
    """Build an AppConfig from the web UI request."""
    base = load_config()

    # Hyperparameters
    hyper = base.hyper
    if any(x is not None for x in [req.N, req.C, req.K]):
        hyper = Hyperparameters(
            N=req.N if req.N is not None else hyper.N,
            C=req.C if req.C is not None else hyper.C,
            K=req.K if req.K is not None else hyper.K,
        )

    # Shared provider
    api_key = req.api_key
    if not api_key:
        api_key = os.environ.get(API_KEY_ENVS.get(req.provider, ""), "")

    shared = ProviderConfig(
        name=req.provider,
        model=req.model or DEFAULT_MODELS.get(req.provider, ""),
        temperature=base.provider.temperature,
        api_key=api_key,
    )

    # Per-agent configs
    if req.multi_agent:

        def _agent(cfg: AgentRunConfig | None) -> AgentProvider:
            if not cfg or not cfg.provider:
                return AgentProvider()
            key = cfg.api_key or os.environ.get(
                API_KEY_ENVS.get(cfg.provider, ""), ""
            )
            return AgentProvider(
                name=cfg.provider,
                model=cfg.model or DEFAULT_MODELS.get(cfg.provider, ""),
                api_key=key,
            )

        agents = AgentConfigs(
            thinking=_agent(req.thinking),
            assistant=_agent(req.assistant),
            review=_agent(req.review),
            cli=_agent(req.cli),
        )
    else:
        agents = AgentConfigs()  # all inherit shared

    return replace(
        base,
        hyper=hyper,
        provider=shared,
        agents=agents,
        skip_lean=req.skip_lean,
    )


async def _execute_run(
    req: RunRequest,
    problem: ProblemSpec,
    resume_from: Path | None = None,
) -> None:
    """Execute the agent pipeline in the background, broadcasting events."""
    try:
        config = _build_config(req)

        desc = f"{config.provider.name}/{config.provider.model}"
        if resume_from:
            await broadcast_thinking(
                "system", 0,
                f"Resuming from {resume_from.name}: {problem.problem_id} with {desc}",
            )
        else:
            await broadcast_thinking(
                "system", 0, f"Starting run: {problem.problem_id} with {desc}"
            )

        if req.multi_agent:
            for role in ["thinking", "assistant", "review", "cli"]:
                acfg = getattr(config.agents, role)
                name = acfg.name or config.provider.name
                model = (
                    acfg.model
                    or config.provider.model
                    or DEFAULT_MODELS.get(name, "")
                )
                await broadcast_thinking(
                    "info", 0, f"  {role}: {name}/{model}"
                )

        # Build initial MEMO snapshot for the UI.
        await broadcast_memo_update(
            {
                "problem": {
                    "problem_id": problem.problem_id,
                    "question": problem.question,
                    "domain": problem.domain,
                    "difficulty_label": problem.difficulty_label,
                },
                "current_roadmap": [],
                "proved_propositions": [],
                "previous_roadmaps": [],
            }
        )

        try:
            from math_agent.orchestrator.coordinator import Coordinator

            coordinator = Coordinator(
                config=config, problem=problem, resume_from=resume_from,
            )

            # Wire coordinator events to the WebSocket broadcast.
            def on_event(event):
                step = getattr(
                    event, "step_index", getattr(event, "step", "?")
                )
                module_name = getattr(event, "module_name", "")
                asyncio.ensure_future(
                    broadcast_thinking(
                        event.event_type,
                        step,
                        event.content,
                        module_name=module_name,
                    )
                )

                # If event contains structured data, broadcast a
                # memo update so the Dialogue panel refreshes.
                metadata = getattr(event, "metadata", {})
                if metadata and any(
                    k in metadata
                    for k in (
                        "current_roadmap",
                        "proved_propositions",
                        "complete_proof",
                    )
                ):
                    memo_data = dict(_state.memo_snapshot)
                    if "current_roadmap" in metadata:
                        memo_data["current_roadmap"] = metadata[
                            "current_roadmap"
                        ]
                    if "proved_propositions" in metadata:
                        memo_data["proved_propositions"] = metadata[
                            "proved_propositions"
                        ]
                    if metadata.get("complete_proof"):
                        memo_data["complete_proof"] = metadata[
                            "complete_proof"
                        ]
                    asyncio.ensure_future(
                        broadcast_memo_update(memo_data)
                    )

            coordinator.on_event(on_event)

            result = await coordinator.run()

            # Final status broadcast.
            status = "SUCCESS" if result.success else "FAILED"
            await broadcast_thinking(
                "result",
                0,
                f"{status} after {result.total_roadmaps} roadmap(s). "
                f"Run dir: {result.run_dir or 'N/A'}",
            )

        except ImportError:
            # Coordinator not yet implemented -- send a placeholder.
            await broadcast_thinking(
                "info",
                0,
                "Coordinator module not yet implemented. "
                "Showing demo data for UI development.",
            )
            await _demo_run(problem)

    except Exception as exc:
        logger.exception("Run failed")
        await broadcast_thinking("error", 0, f"Run failed: {exc}")
    finally:
        _state.running = False
        await broadcast_thinking("system", 0, "Run finished.")


async def _demo_run(problem: ProblemSpec) -> None:
    """Emit demo events for UI development when the coordinator is absent."""
    # Simulate roadmap generation.
    await asyncio.sleep(0.5)
    await broadcast_thinking(
        "roadmap",
        0,
        "Generated proof roadmap with 3 steps.",
    )
    steps = [
        {
            "step_index": 1,
            "description": "Establish base case",
            "status": "UNPROVED",
        },
        {
            "step_index": 2,
            "description": "Prove inductive step",
            "status": "UNPROVED",
        },
        {
            "step_index": 3,
            "description": "Combine results",
            "status": "UNPROVED",
        },
    ]
    await broadcast_memo_update(
        {
            "problem": {
                "problem_id": problem.problem_id,
                "question": problem.question,
                "domain": problem.domain,
                "difficulty_label": problem.difficulty_label,
            },
            "current_roadmap": steps,
            "proved_propositions": [],
            "previous_roadmaps": [],
        }
    )

    # Simulate working through steps.
    for i, step in enumerate(steps):
        await asyncio.sleep(1.0)
        step["status"] = "IN_PROGRESS"
        await broadcast_memo_update(
            {
                "problem": {
                    "problem_id": problem.problem_id,
                    "question": problem.question,
                    "domain": problem.domain,
                    "difficulty_label": problem.difficulty_label,
                },
                "current_roadmap": steps,
                "proved_propositions": [],
                "previous_roadmaps": [],
            }
        )
        await broadcast_thinking(
            "thinking",
            i + 1,
            f"Working on step {i + 1}: {step['description']}...",
        )

        await asyncio.sleep(1.5)
        await broadcast_thinking(
            "reasoning",
            i + 1,
            f"Applying proof technique for step {i + 1}. "
            f"Reasoning about {step['description']}...",
        )

        await asyncio.sleep(1.0)
        step["status"] = "PROVED"
        await broadcast_memo_update(
            {
                "problem": {
                    "problem_id": problem.problem_id,
                    "question": problem.question,
                    "domain": problem.domain,
                    "difficulty_label": problem.difficulty_label,
                },
                "current_roadmap": steps,
                "proved_propositions": [
                    {
                        "prop_id": f"P{j + 1}",
                        "statement": steps[j]["description"],
                        "source": f"Roadmap A, step {j + 1}",
                    }
                    for j in range(i + 1)
                ],
                "previous_roadmaps": [],
            }
        )
        await broadcast_thinking(
            "verified",
            i + 1,
            f"Step {i + 1} proved and self-verified.",
        )


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket connection for live event streaming."""
    await ws.accept()
    _ws_clients.add(ws)
    logger.info("WebSocket client connected (%d total)", len(_ws_clients))

    # Send the current state snapshot so a late-joining client catches up.
    try:
        if _state.memo_snapshot:
            await ws.send_text(
                json.dumps(
                    {"type": "memo_update", "data": _state.memo_snapshot}
                )
            )
        # Replay recent events (last 50).
        for event in _state.events[-50:]:
            await ws.send_text(json.dumps({"type": "thinking", "data": event}))

        await ws.send_text(
            json.dumps(
                {
                    "type": "status",
                    "data": {
                        "running": _state.running,
                        "provider": _state.provider,
                        "model": _state.model,
                    },
                }
            )
        )
    except Exception:
        _ws_clients.discard(ws)
        return

    # Keep the connection open, reading client messages.
    try:
        while True:
            data = await ws.receive_text()
            # Client messages can be used for future features (e.g. cancel).
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)
        logger.info(
            "WebSocket client disconnected (%d remaining)", len(_ws_clients)
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the web server on port 8000."""
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger.info("Starting Math Agent web UI at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
