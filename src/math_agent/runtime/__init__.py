"""Runtime layer for session-backed CLI and API execution."""

from .base import (
    AgentRuntimeSession,
    CommandExecutionError,
    InputTooLargeError,
    MAX_INPUT_CHARS,
    RuntimeInvocation,
    RuntimeMessage,
    RuntimeResult,
    RuntimeSessionState,
    extract_json,
    render_transcript,
)
from .factory import build_backend, build_role_sessions

__all__ = [
    "AgentRuntimeSession",
    "CommandExecutionError",
    "InputTooLargeError",
    "MAX_INPUT_CHARS",
    "RuntimeInvocation",
    "RuntimeMessage",
    "RuntimeResult",
    "RuntimeSessionState",
    "build_backend",
    "build_role_sessions",
    "extract_json",
    "render_transcript",
]
