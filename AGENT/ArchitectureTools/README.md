# Architecture Visualization Tools

Interactive graph visualization of the current `Math Agent` architecture.

## Quick Start

```bash
cd "/Users/wsr_sg/projects/Math Agent/AGENT/ArchitectureTools"
python3 -m http.server 8091
# Open http://localhost:8091
```

## Files

- `architecture.json` — graph data. Source of truth for the visualizer.
- `index.html` — browser visualizer for `architecture.json`.
- `ArchitectureDiagram.md` — concise human-readable architecture summary.

## Edit Rule

Do not read the whole `architecture.json` file unless you are replacing the full graph.

For targeted edits:

1. Find the relevant section or node ID with `rg -n`.
2. Read only the surrounding block with `sed -n`.
3. Edit only the affected node, edge, or agent entry.
4. Validate the JSON after the edit.

Examples:

```bash
rg -n '"resume_verify"|"lean_workspace"|"review"' architecture.json
sed -n '80,180p' architecture.json
python3 -c "import json; json.load(open('architecture.json')); print('OK')"
```

## JSON Structure

Top-level section order:

1. `meta`
2. `agents`
3. `groups`
4. `nodes`
5. `edges`

### Node Schema

```json
"node_id": {
  "label": "Display name",
  "group": "group_id",
  "level": 0,
  "agent": "agent_id or null",
  "function": "function_name() or null",
  "file": "path or path:lines or null",
  "prompt": "Exact prompt text or null",
  "description": "What this node does"
}
```

Rules:

- `prompt` must match the actual code when the node represents an LLM call.
- `agent` must reference an entry in `agents`, or be `null`.
- `group` must reference an entry in `groups`.
- Keep `level` monotone along the forward path when possible.

### Edge Schema

```json
{
  "from": "source_node_id",
  "to": "target_node_id",
  "label": "Short edge label",
  "description": "Longer tooltip description"
}
```

## Current Graph Scope

The graph reflects the migrated architecture:

- single CLI entrypoint
- unified runtime layer for CLI and API backends
- Phase 1 proof search only
- optional Lean `check` mode using a shared workspace
- review and blind falsifier validation

It intentionally does not model:

- removed web app
- removed Phase 2 Lean formalization pipeline

## Validation Checklist

- valid JSON
- every node `agent` exists
- every node `group` exists
- every edge `from`/`to` exists
- prompt text matches code for LLM nodes
