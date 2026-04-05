"""FastAPI web server with WebSocket streaming for the two-panel Math Agent UI."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from math_agent.config import load_config, AppConfig
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
# Pydantic request models
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    """JSON body for POST /api/run."""

    provider: str = "anthropic"
    model: str = ""
    api_key: str = ""
    problem_id: str | None = None
    custom_question: str | None = None
    custom_domain: str = "general"


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


@app.post("/api/run")
async def start_run(req: RunRequest):
    """Start a new agent run in the background."""
    if _state.running:
        return JSONResponse(
            {"error": "A run is already in progress."},
            status_code=409,
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
    else:
        return JSONResponse(
            {"error": "Provide either problem_id or custom_question."},
            status_code=400,
        )

    # Resolve model defaults.
    provider = req.provider
    model = req.model
    if not model:
        defaults = {
            "anthropic": "claude-opus-4-0626",
            "openai": "o3",
            "deepseek": "deepseek-reasoner",
            "gemini": "gemini-2.5-pro",
        }
        model = defaults.get(provider, "")

    # Resolve API key: prefer the request body, then fall back to env.
    api_key = req.api_key
    if not api_key:
        env_keys = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "gemini": "GEMINI_API_KEY",
        }
        api_key = os.environ.get(env_keys.get(provider, ""), "")

    # Reset state and launch the run.
    _state.running = True
    _state.problem = problem
    _state.provider = provider
    _state.model = model
    _state.memo_snapshot = {}
    _state.notes_content = ""
    _state.events = []
    _state.started_at = time.time()

    asyncio.create_task(_execute_run(provider, model, api_key, problem))

    return JSONResponse(
        {
            "status": "started",
            "problem_id": problem.problem_id,
            "provider": provider,
            "model": model,
        }
    )


# ---------------------------------------------------------------------------
# Background execution
# ---------------------------------------------------------------------------


async def _execute_run(
    provider: str,
    model: str,
    api_key: str,
    problem: ProblemSpec,
) -> None:
    """Execute the agent pipeline in the background, broadcasting events."""
    from math_agent.main import create_client

    try:
        config = load_config()

        await broadcast_thinking(
            "system", 0, f"Starting run: {problem.problem_id} with {provider}/{model}"
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

            client = create_client(
                provider, model, api_key, config.provider.temperature
            )
            coordinator = Coordinator(config, client, problem)

            # Wire coordinator events to the WebSocket broadcast.
            def on_event(event):
                step = getattr(event, "step_index", getattr(event, "step", "?"))
                module_name = getattr(event, "module_name", "")
                asyncio.ensure_future(
                    broadcast_thinking(
                        event.event_type,
                        step,
                        event.content,
                        module_name=module_name,
                    )
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
        {"step_index": 1, "description": "Establish base case", "status": "UNPROVED"},
        {"step_index": 2, "description": "Prove inductive step", "status": "UNPROVED"},
        {"step_index": 3, "description": "Combine results", "status": "UNPROVED"},
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
                json.dumps({"type": "memo_update", "data": _state.memo_snapshot})
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
        logger.info("WebSocket client disconnected (%d remaining)", len(_ws_clients))


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
