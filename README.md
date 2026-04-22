# Math Agent

Math Agent is a CLI-first math proof agent with optional Lean 4 verification.

It is designed around one main workflow:

1. generate proof roadmaps,
2. execute and verify steps,
3. review the compiled proof,
4. try to break the result with a blind falsifier,
5. optionally use Lean to type-check theorem statements and proof sketches.

## Environment Setup

### Python

Use Python 3.12+.

```bash
cd "/Users/wsr_sg/projects/Math Agent"
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

### Backends

Default backend is Codex CLI.

Supported backends:

- CLI: `codex`, `claude`
- API: `openai`, `anthropic`, `deepseek`, `gemini`

If you use an API backend, set the matching key:

```bash
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
export DEEPSEEK_API_KEY=...
export GEMINI_API_KEY=...
```

### Lean (Optional)

Lean is optional. You only need it for `--lean-mode check`.

Install `elan` / `lake` normally. The first Lean-enabled run bootstraps a shared workspace at:

```text
.cache/lean-workspace
```

That workspace is reused across runs, so Mathlib cache is not downloaded into every run directory.

## Quick Start

Interactive mode:

```bash
math-agent
```

One-shot custom problem:

```bash
math-agent --question "Prove that 1 + 3 + \u2026 + (2n - 1) = n^2."
```

Use a specific backend:

```bash
math-agent --question "Prove x = x." --backend codex
math-agent --question "Prove x = x." --backend openai --model o3
```

Enable Lean statement/sketch checks:

```bash
math-agent --question "Prove x = x." --lean-mode check
```

Resume a previous run:

```bash
math-agent --resume <run-directory>
```

Run the evaluation harness:

```bash
python -m math_agent.eval.harness
```

## How The Project Is Designed

The codebase keeps the original `math_agent` package name but uses the newer v3-style architecture internally.

- `src/math_agent/main.py` handles CLI entry, backend selection, resume, and eval dispatch.
- `src/math_agent/config.py` resolves shared runtime config plus per-agent overrides.
- `src/math_agent/runtime/` provides a unified execution layer for both CLI and API backends.
- `src/math_agent/orchestrator/coordinator.py` manages run setup, shared Lean workspace preparation, and top-level orchestration.
- `src/math_agent/orchestrator/phase1.py` runs the roadmap / step / review / falsifier loop.
- `src/math_agent/documents/` stores persistent proof-search memory in MEMO and NOTES.
- `src/math_agent/lean/` provides optional Lean statement/sketch verification only.

The active agent roles are:

- Thinking Agent: proof planning, step execution, self-verification, repair.
- Formalizer Agent: Lean-oriented theorem and lemma sketch generation.
- Assistant Agent: MEMO/NOTES maintenance and proof compilation.
- Review Agent: transcript-blind proof review.
- Falsifier Agent: blind adversarial Python-backed checking.

There is no web app and no full Lean Phase 2 formalization pipeline in this repository.
