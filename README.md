# Math Research Agent

An autonomous agent that proves mathematical theorems through structured depth-first search, with optional Lean 4 formal verification.

Given a math problem, the agent generates proof strategies, works through each step with self-verification, diagnoses failures, and iterates — accumulating knowledge across attempts via a persistent memory system (MEMO).

## Features

- **Depth-first proof search** — commit to one strategy, learn from failures, then pivot with knowledge
- **Persistent memory (MEMO)** — proved propositions, refuted claims, and failure diagnoses survive across context resets and even across separate runs
- **5 specialized agents** — Thinking (proves), Assistant (documents), Review (verifies), Blind Falsifier (counterexamples via Python sandbox), CLI (Lean 4)
- **Failure diagnosis** — classifies failed steps as *false proposition*, *logical gap*, or *insufficient technique* to prevent repeating mistakes
- **Multi-provider LLM** — OpenAI, Anthropic, DeepSeek, Google Gemini; mix different models per agent role
- **Resume from any run** — crash recovery, model switching, iterative refinement
- **Lean 4 + Mathlib** formalization with sorry-elimination
- **Web UI** with live roadmap tracking and thinking process streaming
- **43 built-in problems** across 6 difficulty levels

## Quick Start

```bash
pip install -e .

# Set at least one provider API key
export ANTHROPIC_API_KEY=sk-...
# or: OPENAI_API_KEY, DEEPSEEK_API_KEY, GEMINI_API_KEY

# CLI — interactive wizard
math-agent

# Web UI — three-panel interface at http://127.0.0.1:8000
math-agent-web
```

## How It Works

### Phase 1: Mathematical Proof

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   Problem ──→ Generate 3 Roadmaps ──→ Select Best           │
│                                          │                  │
│              ┌───────────────────────────↓──────────┐       │
│              │  For each step:                      │       │
│              │    1. Prove it (Thinking Agent)       │       │
│              │    2. Self-verify                     │       │
│              │    3. On failure: diagnose & record   │       │
│              │    4. Update MEMO                     │       │
│              └──────────────────────────────────────┘       │
│                          │                                  │
│                    All steps proved                          │
│                          │                                  │
│              ┌───────────↓──────────────┐                   │
│              │  Review:                 │                   │
│              │    1. Contextual review  │                   │
│              │    2. Gap repair (×2)    │                   │
│              │    3. Blind falsifier    │                   │
│              └─────────────────────────┘                    │
│                          │                                  │
│                    Pass ──→ Phase 2 (Lean 4)                │
│                    Fail ──→ New roadmap with updated MEMO    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Key mechanisms:**

- **Roadmap generation** — first attempt generates 3 candidates and picks the most concrete; subsequent attempts are informed by everything learned so far
- **Step failure diagnosis** — when a step fails after retries, the agent classifies *why* (false claim? logical gap?) and records it so future roadmaps don't repeat the mistake
- **Roadmap viability check** — if a failed step is critical to later steps, the roadmap is abandoned immediately instead of wasting compute
- **Blind Falsifier** — receives only the problem statement and claimed answer (zero proof context), generates Python code to check small cases and boundary conditions
- **Progressive compression** — context is managed in 4 layers; full reset is a last resort, not the default

### Phase 2: Lean 4 Formalization

The proved theorem is split into Lean modules, each compiled against Mathlib. The CLI Agent eliminates sorry's module by module, accepting well-known textbook results as external claims (axioms) when needed.

### MEMO: Persistent Memory

The MEMO is what makes multi-attempt proving work. It records:

```
Current Roadmap:
  Step 1: Small cases ........................ [PROVED]
  Step 2: Odd prime analysis ................. [PROVED]
  Step 3: Even case .......................... [FAILED]
    Diagnosis: [FALSE_PROPOSITION] "odd prime factor ⟹ n is odd"

Proved Propositions (reusable):
  - For n ≤ 100, only {1, 2, 4, 12} satisfy the condition

Refuted Propositions (DO NOT RETRY):
  - "If n has an odd prime factor p, then n is odd"
    Counterexample: n = 12 = 2² · 3
```

MEMO survives context resets, run crashes, model switches, and even transfers between runs via the resume feature.

## Configuration

### Per-Agent Models

Each agent can use a different LLM. Configure in TOML:

```toml
[provider]
name = "anthropic"
model = "claude-opus-4-0626"

[agents.thinking]
name = "openai"
model = "o3"

[agents.assistant]
name = "gemini"
model = "gemini-2.5-flash"
```

### Lean 4 (Phase 2)

Phase 2 requires [elan](https://github.com/leanprover/elan) (the Lean version manager):

```bash
# Install elan
curl https://elan-init.trycloudflare.com -sSf | sh

# Verify
lake --version
```

No manual `LEAN_PATH` setup needed — the agent scaffolds a full Lake project per run with Mathlib pinned to the configured toolchain. Lean settings in TOML:

```toml
[lean]
toolchain = "leanprover/lean4:v4.28.0"   # Lean version
mathlib = true                            # include Mathlib dependency
```

Set `skip_lean = true` (or check "Skip Phase 2" in the Web UI) to run mathematical proofs without Lean formalization.

### Hyperparameters

| Param | Default | Meaning |
|-------|---------|---------|
| **N** | 7 | Steps per roadmap |
| **C** | 8 | Context compression interval |
| **K** | 7 | Abandon after K iterations without progress |

- **N (steps per roadmap)** — How many steps each proof roadmap is divided into. Lower N means coarser steps (each step does more work); higher N means finer steps (easier to verify individually, but more overhead). For simple problems, N = 3–5 is enough. For hard problems (L4+), N = 7–10 gives the agent room to decompose complex arguments.

- **C (compression interval)** — After every C execution loops, the system checks context pressure and triggers progressive compression if needed. Lower C means more aggressive compression (saves tokens but may lose detail); higher C lets the agent work longer before compressing. The default of 8 works well for most models' context windows.

- **K (diminishing returns window)** — If the agent makes no progress (no new steps proved, no new insights) for K consecutive iterations, the current roadmap is abandoned and a new one is generated. This prevents the agent from spinning on a stuck approach. Lower K gives up faster; higher K gives the agent more patience. There is no fixed max-rounds limit — K is the only termination criterion per roadmap.

### Resume

```bash
math-agent --resume 20260406_085108
math-agent --resume 20260406_085108 --provider deepseek --model deepseek-chat
```

Or use the Web UI: select "Resume from previous run" in the problem source dropdown.

## Test Highlights

| Problem | Level | Model | Result |
|---------|-------|-------|--------|
| Uniform Boundedness Principle | L4 | Claude Opus | Single-roadmap solve |
| Krull Intersection Theorem | L3 | Gemini Flash | Solve + successful resume |
| IMO 2024 Shortlist N1 | L4+ | DeepSeek Chat | Correct answer every attempt |
| RMM 2026 P2 (factorial divisibility) | L5 | Gemini 3.1 Pro | Complete gap-free proof |
| RMM 2026 P6 (permutation floor inequality) | L6 | Gemini 3.1 Pro | Complete proof, 2 roadmaps |

**IMO 2024 N1:** DeepSeek-chat (a non-reasoning model) with the MEMO architecture correctly solved the problem in every attempt. DeepSeek Reasoning (R1) in AlphaEvolve and Gemini chatbot could not solve it standalone.

**RMM 2026 P2** (L5): The agent produced a complete, gap-free 6-step proof via involution analysis. Gemini 3.1 Pro in the web interface (single-shot, no architecture) found the correct answer but left 4 significant gaps. The architecture's multi-step verification closed every gap the standalone model could not.

**RMM 2026 P6** (L6 — competition extreme): A 9-step proof via Erdős–Szekeres poset analysis, Dilworth partition, grid bijection with (−d,l)-lex ordering, and Gale's theorem for bucket feasibility. The first roadmap was rejected by the blind falsifier (found a concrete counterexample k=3, X=(2,5,7,8) where the constructed permutation admitted an extra monotone subsequence). The second roadmap fixed the construction with refined placement constraints and proved uniqueness by downward induction. GPT Pro web failed this problem; Gemini 3.1 Pro in the web interface could not produce any meaningful progress. The MEMO architecture with the same Gemini 3.1 Pro API produced a complete, rigorous proof. The proof was verified by Opus 4.6 and GPT 5.4 xhigh.

## Project Structure

```
src/math_agent/
├── agents/          Thinking, Assistant, Review, Falsifier, CLI
├── orchestrator/    Phase 1 & 2 execution loops, coordinator
├── documents/       MEMO, NOTES, module MEMO persistence
├── context/         Progressive compression, diminishing returns
├── llm/             OpenAI, Anthropic, DeepSeek, Gemini clients
├── lean/            Lean 4 compiler, Mathlib search, external claims
├── problem/         43 built-in problems (L1–L6)
├── eval/            Evaluation harness
└── web/             Three-panel web UI (HTML/CSS/JS)
```

## Difficulty Levels

| Level | Label | Benchmark |
|-------|-------|-----------|
| L1–L2 | Toy | Any/most models solve in 1 roadmap |
| L3 | PhD qualifying exam | Standard graduate-level |
| L4 | Beyond QE / Olympiad | IMO shortlist, advanced theorems |
| L5 | Research / Competition hard | Research theorems, RMM P1–P4 |
| L6 | Competition extreme | Problems top models cannot solve standalone |

## License

[Apache 2.0](LICENSE)
