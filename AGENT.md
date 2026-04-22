# Math Agent

Agent-facing repo guide. Keep this concise and operational.

## Start Here

Before broad exploration, read:

1. `AGENT/codebase-graph/codebase-graph.json`
2. `AGENT/ArchitectureTools/architecture.json`

If the graph may be stale after structural edits, regenerate it:

```bash
python AGENT/codebase-graph/build_codebase_graph.py
```

## How To Use The Codebase Graph

Use `AGENT/codebase-graph/codebase-graph.json` as the structural index.

- `task_routes`: fastest way to find the owning files for a task area.
- `execution_path`: primary CLI -> config -> coordinator -> Phase 1 flow.
- `entrypoints`: user-visible commands from `pyproject.toml`.
- `files`: file summaries, tags, module names.
- `symbols`: top-level classes/functions/methods with defining file + line.
- `edges`: import, test, route, and entrypoint links.

Typical lookups:

- CLI / eval flow: `task == "cli_launch_or_eval"`
- runtime layer: `task == "runtime_backends"`
- Lean integration: `task == "lean_verification"`
- proof orchestration: `task == "phase1_orchestration"`
- regression coverage: `task == "tests"`

Use the graph to narrow the search space first, then open only the relevant files.

## Architecture

Current architecture:

- package root: `src/math_agent`
- single CLI entrypoint: `math-agent`
- Phase 1 proof search only
- active agents: thinking, formalizer, assistant, review, falsifier
- runtime layer supports CLI and API backends
- Lean is optional `off` / `check`
- Lean cache lives in shared `.cache/lean-workspace`

Removed architecture:

- web app
- full Lean Phase 2 formalization
- legacy `cli` agent role

## High-Signal Files

- `src/math_agent/main.py`
- `src/math_agent/config.py`
- `src/math_agent/orchestrator/coordinator.py`
- `src/math_agent/orchestrator/phase1.py`
- `src/math_agent/runtime/`
- `src/math_agent/agents/`
- `src/math_agent/lean/`
- `src/math_agent/documents/memo.py`
- `src/math_agent/problem/spec.py`

## Edit Rules

- Preserve the current package/import surface as `math_agent`.
- Preserve CLI entrypoint `math-agent`.
- Keep Lean modes semantically limited to `off` and `check`.
- Do not reintroduce per-run Lean cache/workspace copies.
- Prefer targeted reads guided by the codebase graph and architecture graph.
- Update `AGENT/codebase-graph/codebase-graph.json` after major file-layout changes.
- Update `AGENT/ArchitectureTools/architecture.json` when the execution flow or prompt surfaces change.
