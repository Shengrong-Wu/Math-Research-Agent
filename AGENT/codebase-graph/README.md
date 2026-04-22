# Codebase Graph

This folder contains a machine-readable structural index for `Math Agent`.

## Generate

From the project root:

```bash
python AGENT/codebase-graph/build_codebase_graph.py
```

This writes:

- `AGENT/codebase-graph/codebase-graph.json`

## What It Covers

- tracked code/config/docs under `src/`, `tests/`, `configs/`
- root files: `README.md`, `AGENT.md`, `.gitignore`, `pyproject.toml`
- Python symbol inventory: classes, functions, methods
- internal import edges
- test-to-source edges
- console entrypoints from `pyproject.toml`
- curated task routes for the migrated architecture

The graph is intentionally structural. It does not include run-state artifacts under `runs/` and it excludes `AGENT/` tooling internals to avoid recursive indexing.

## Main Sections

- `meta`
- `entrypoints`
- `execution_path`
- `task_routes`
- `files`
- `symbols`
- `edges`
- `stats`

## How To Use It

Use the graph before broad repo exploration.

- Start with `task_routes` to find the owning files for a task area.
- Use `execution_path` for the main CLI -> coordinator -> Phase 1 flow.
- Use `entrypoints` to find user-visible commands.
- Use `symbols` to find defining files and line numbers for top-level APIs.
- Use `edges` to trace imports and test coverage.

Typical queries:

- CLI launch / eval path: `task_routes[task=="cli_launch_or_eval"]`
- runtime backends: `task_routes[task=="runtime_backends"]`
- optional Lean verification: `task_routes[task=="lean_verification"]`
- high-signal regression tests: `task_routes[task=="tests"]`

Regenerate the graph after large refactors that move files, rename modules, or replace entrypoints.
