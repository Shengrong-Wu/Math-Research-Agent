<!-- SECTION: system_prompt -->
You are a Thinking Agent in a mathematical proof system. Your role is to reason carefully about mathematical proofs, generate proof strategies, work through individual proof steps with rigour, and verify your own work. Always show your reasoning clearly. When you prove a step, write out the full logical argument.

<!-- SECTION: roadmap_generation -->
Problem:
{problem_question}

{memo_block}{divergence_block}Generate exactly {count} distinct proof roadmap(s). For each roadmap, provide:
  - "approach": a concise description of the proof strategy
  - "steps": a JSON array of STEP OBJECTS with keys:
      - "description": what to prove in that step
      - "obligations": JSON array chosen from
          ["necessary_direction", "sufficiency_direction", "existence_or_construction", "boundary_or_small_cases", "final_target_link"]
    Example:
      [{{"description": "Derive the necessary constraints", "obligations": ["necessary_direction"]}}]
  - "reasoning": why this approach is promising

STEP DECOMPOSITION RULES:
  - Use {n_min} to {n_max} steps. Each step should be a coherent argument unit that an advanced reasoner can carry out and verify in one pass — neither so granular that natural arguments are split mid-thought, nor so coarse that multiple distinct hard ideas are bundled together.
  - Each step must be independently verifiable.
  - The hard parts of the proof should be explicit named steps, not buried in a final 'put it all together' step.
  - If a step involves case analysis with substantively more than 3 different cases, split it.
  - Do NOT use vague steps like 'combine results', 'finish by standard argument', or 'after routine verification' — these hide the actual work and must be replaced with explicit steps.

IMPORTANT: If the problem asks you to 'find all', 'characterize', 'determine which', or 'classify', your roadmap MUST include:
  - A step that derives NECESSARY conditions (constraints on solutions)
  - A step that explicitly verifies SUFFICIENCY (that each candidate actually satisfies the FULL original condition for ALL sub-conditions)
  - A step that checks small cases or boundary cases computationally
A proof that only establishes necessary conditions is INCOMPLETE.

IMPORTANT: If the problem states an equivalence ('if and only if', 'iff', 'equivalent') your roadmap MUST include explicit coverage of BOTH directions. A roadmap that proves only one direction is INCOMPLETE.

IMPORTANT: If the theorem requires existence or construction ('there exists', 'construct', 'build', 'define an object', 'exhibit'), your roadmap MUST include:
  - A step that constructs or exhibits the required object
  - A step that verifies the constructed object satisfies the FULL target property
An existence proof that derives only constraints is INCOMPLETE.

Respond with a JSON array of roadmap objects and nothing else.
CRITICAL: The "steps" field must be an array of STEP OBJECTS, not bare strings.

<!-- SECTION: divergence_instruction -->
CRITICAL — STRATEGIC DIVERGENCE REQUIRED.

{prior_attempt_count} previous roadmap attempt(s) have already been abandoned. Your new roadmap MUST use a STRATEGIC PARADIGM that is fundamentally different from every previous attempt. Do NOT reword a previous approach or re-order its steps.

Previous attempts and why they were abandoned:
{previous_attempts}

Example strategic paradigms (pick ONE that is NOT represented above — if you cannot find a fundamentally different paradigm, state that explicitly in your reasoning):
  - Explicit combinatorial construction
  - Abstract existence via matching / flow theorems (Hall, König, Menger)
  - Extremal / uniqueness argument forcing structure
  - Induction on a structural parameter (with the parameter NAMED, not 'size')
  - Contradiction via invariant or potential function
  - Double counting or bijective proof
  - Probabilistic / algebraic / generating-function approach
  - Graph-theoretic reformulation

If the last 2+ attempts all hit the SAME KIND of failure (e.g. kept failing to write explicit formulas, kept missing the same case, kept tripping the same review objection), treat that as a strong signal to abandon that ENTIRE paradigm — not just the specific wording of the steps that failed.

<!-- SECTION: split_overloaded_step -->
Problem:
{problem_question}

Overloaded roadmap step:
{step_description}

This step hides work behind vague language. Split it into 2 to 4 more focused roadmap steps that each name a specific argument or computation. Each new step should be a coherent argument unit a strong reasoner can carry out and verify in one pass — do NOT shred the work below the natural argument scope.

Return only a JSON array of strings.

<!-- SECTION: regenerate_macro_step -->
Problem:
{problem_question}

Macro-step description:
{macro_description}
Deliverable:
{macro_deliverable}

Completed macro-step deliverables:
{completed_macro_summaries}

Failed sub-steps to avoid repeating:
{failed_sub_steps}

Regenerate ONLY this macro-step as 3 to 8 focused sub-steps that still achieve the same deliverable. Each sub-step should be a coherent argument unit a strong reasoner can carry out and verify in one pass. Return only a JSON array of strings.

<!-- SECTION: step_prove -->
Problem: {problem_question}

Overall proof roadmap:
{roadmap_summary}

{context_block}Step {step_number}: {step_description}

Prove this step. Show all reasoning and write a complete, rigorous proof for this step.

<!-- SECTION: step_verify -->
Problem: {problem_question}

Overall proof roadmap:
{roadmap_summary}

Step {step_number}: {step_description}

Candidate proof:
{proof_detail}

Determine whether the candidate proof establishes the EXACT requested step.

Respond in this exact format:
OUTCOME: <PROVED | REFUTED_STEP | PROVED_DIFFERENT_CLAIM | FAILED>
EXPLANATION: <1-3 sentences>
DERIVED_CLAIM: <if PROVED_DIFFERENT_CLAIM, state the claim proved; otherwise NONE>
FALSE_CLAIM: <if REFUTED_STEP, state the false claim; otherwise NONE>

Rules:
- PROVED means the proof correctly proves the exact stated step.
- REFUTED_STEP means the proof shows the step is false or gives a counterexample.
- PROVED_DIFFERENT_CLAIM means the argument proves a different or weaker claim than the requested step.
- FAILED means the proof has logical gaps, unjustified claims, or does not reach the claimed conclusion.
- A proof that refutes the step is NOT PROVED.

<!-- SECTION: verify_proved_step -->
Problem: {problem_question}

The following proof was previously written for Step {step_index}:
Step {step_index}: {step_description}

Proof:
{proof_detail}

Check whether this proof is correct, rigorous, and proves the EXACT stated step. Look for logical gaps, unjustified claims, errors in reasoning, missing cases, and off-target conclusions.

If correct, respond with VERIFIED and a brief confirmation.
If not correct, respond with INVALID and explain why. A proof that establishes a different claim or shows the step is false must be marked INVALID.

<!-- SECTION: formalize_statement -->
Problem: {problem_question}

Proof approach: {approach}

Write a Lean 4 theorem statement for this problem. Include:
- `import Mathlib.Tactic` (and other necessary imports)
- The theorem statement with the correct type signature
- A `sorry` proof body

Return ONLY the Lean 4 code, no explanation.

<!-- SECTION: formalize_step_sketch -->
Problem: {problem_question}

Step just proved: {step_description}

Previously proved propositions:
{proved_propositions_text}

Write a Lean 4 lemma sketch for this step. Include:
- `import Mathlib.Tactic` (and other necessary imports)
- The lemma statement with the correct type signature
- A `sorry` proof body

Return ONLY the Lean 4 code, no explanation.

<!-- SECTION: repair_proof -->
Problem: {problem_question}

Your proof was reviewed and found to be MOSTLY correct, but has specific gaps that need fixing.

Current proof:
{complete_proof}

GAPS FOUND BY REVIEWER:
{gaps_text}

REVIEWER'S REASONING:
{reviewer_reasoning}

INSTRUCTIONS:
1. Do NOT rewrite the entire proof from scratch.
2. Keep everything that is correct.
3. Fix ONLY the specific gaps identified above.
4. The reviewer may have suggested specific fixes -- use them.
5. If a gap is about a wrong argument for a specific case, replace that argument with a correct one.
6. Write the COMPLETE repaired proof (not just the fix).

Write the repaired proof now.

<!-- SECTION: diagnose_step_failure -->
Problem: {problem_question}

Step {step_index}: {step_description}

This step FAILED after {error_count} attempts. Here are the verification errors from each attempt:
{errors_text}

Diagnose WHY this step failed. Classify as one of:
- FALSE_PROPOSITION: The claim in this step is actually FALSE. State the specific false claim.
- LOGICAL_GAP: The claim might be true, but the proof attempts all had logical gaps that could not be bridged.
- INSUFFICIENT_TECHNIQUE: The claim is likely true but requires a technique or lemma not available in the current approach.
- UNCLEAR: Cannot determine the cause.

Respond in this exact format:
DIAGNOSIS: <one of the four categories above>
EXPLANATION: <1-2 sentences explaining why>
FALSE_CLAIM: <if FALSE_PROPOSITION, state the specific false claim that future roadmaps must avoid. Otherwise write NONE>

<!-- SECTION: reevaluate_roadmap -->
Problem: {problem_question}

Overall roadmap:
{roadmap_summary}

Completed steps:
{completed_steps_json}

Remaining steps:
{remaining_steps_json}

Required theorem obligations:
{required_obligations_json}

Given that the completed steps are proved, answer BOTH:
1. Do the remaining steps still make sense locally?
2. If ALL remaining steps were proved, would the roadmap still constitute a COMPLETE proof of the target theorem, including every required obligation above?

Respond in this exact format:
STATUS: <ON_TRACK | NEEDS_UPDATE | NEEDS_EXTENSION>
MISSING_OBLIGATIONS: <JSON array of obligation strings, or []>
UPDATED_STEPS: <JSON array of step objects with keys index, description, obligations>
EXPLANATION: <brief explanation>

Rules:
- ON_TRACK means the remaining steps are still plausible and theorem coverage is complete.
- NEEDS_UPDATE means the remaining steps need rewriting but no new obligation category is missing.
- NEEDS_EXTENSION means the roadmap is locally coherent but theorem coverage is incomplete; add the missing steps instead of silently dropping the obligation.
- UPDATED_STEPS may rewrite existing remaining steps and may append new ones. If you add a new step, either omit its index or use a new larger index.
- Every UPDATED_STEPS object must include an obligations array using the canonical obligation keys whenever applicable.
- Never delete a necessary/sufficiency/existence/final-synthesis obligation without explicitly replacing it.

<!-- SECTION: reevaluate_after_failure -->
Problem: {problem_question}

Overall roadmap:
{roadmap_summary}

Completed steps (PROVED):
{completed_steps_json}

FAILED step:
{failed_step_json}

Remaining steps (not yet attempted):
{remaining_steps_json}

The failed step could NOT be proved after multiple attempts.

Analyze whether the remaining steps DEPEND on the failed step. Consider:
1. Do any remaining steps use the result of the failed step?
2. Can the remaining steps be restructured to work without it?
3. Is the failed step a critical link in the proof chain?

If the remaining steps can be restructured to work without the failed step, respond with NEEDS_UPDATE and provide updated step objects with description + obligations as a JSON array.
If the failed step is critical and the roadmap cannot succeed without it, respond with ABANDON and explain why.
Format: Start your response with NEEDS_UPDATE or ABANDON.

<!-- SECTION: completeness_check -->
Problem: {problem_question}

Overall roadmap:
{roadmap_summary}

Proved step summaries:
{proved_steps_json}

Required theorem obligations:
{required_obligations_json}

Determine whether the proved steps already amount to a COMPLETE proof strategy for the original theorem.

Respond in this exact format:
STATUS: <COMPLETE | INCOMPLETE>
MISSING_OBLIGATIONS: <JSON array of obligation strings, or []>
MISSING_STEPS: <JSON array of missing step descriptions, or []>
EXPLANATION: <brief explanation>

Rules:
- COMPLETE means the proved steps cover every logical branch/case/direction required by the target theorem.
- INCOMPLETE means something essential is still missing (for example the converse direction, a construction step, boundary cases, or the final theorem linkage).
- If INCOMPLETE, provide concrete missing step descriptions that could be appended to the roadmap.
