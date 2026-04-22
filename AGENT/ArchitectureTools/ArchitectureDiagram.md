# Math Agent Architecture

This document summarizes the current architecture shown in `architecture.json`.

## Core Flow

1. `math-agent` starts in `src/math_agent/main.py`.
2. Config is loaded and runtime backends are resolved.
3. `Coordinator.run()` creates the run directory, writes `summary.json`, optionally prepares the shared Lean workspace, and builds role sessions.
4. `Phase1Runner.run()` drives roadmap generation, step work, resume logic, review, and falsification.
5. Successful runs write proof artifacts under `runs/<timestamp>/`.

## Active Agents

- Thinking Agent: roadmap generation, step proving, self-verification, roadmap repair.
- Formalizer Agent: Lean-oriented statement and sketch generation.
- Assistant Agent: MEMO / NOTES maintenance, proposition extraction, proof compilation.
- Review Agent: transcript-blind proof review with explicit verdict.
- Falsifier Agent: blind adversarial Python-backed checking.
- Lean Toolplane: optional statement/sketch verification, no LLM.

## Runtime Layer

The runtime layer supports:

- CLI backends: `codex`, `claude`
- API backends: `openai`, `anthropic`, `deepseek`, `gemini`

`build_role_sessions()` resolves per-role overrides and constructs one session per active agent role.

## Lean Verification

Lean is optional and defaults to `off`.

When `lean_mode == "check"`:

- the coordinator prepares `.cache/lean-workspace`
- workspace bootstrap is keyed by a stamp file
- `lake update` and `lake exe cache get` are skipped when the stamp matches
- Phase 1 uses Lean only for theorem statement and step sketch checks

There is no Phase 2 full formalization pipeline in this repository.

## Important State

- `MEMO.md` / `MEMO.json`: durable proof-search state
- `NOTES.md`: proof details
- `summary.json`: run-level result and runtime telemetry
- `agent_runtime/`: backend invocation artifacts
