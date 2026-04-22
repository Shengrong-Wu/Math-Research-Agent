import asyncio
import json

from math_agent.agents.thinking import ThinkingAgent
from math_agent.runtime import RuntimeMessage
from conftest import MockRuntimeSession

class TestThinkingAgent:
    def test_generate_roadmaps_first_attempt(self):
        roadmap_json = json.dumps([{
            "approach": "Induction on n",
            "steps": ["Base case n=1", "Inductive hypothesis", "Inductive step"],
            "reasoning": "Standard induction approach"
        }])
        runtime = MockRuntimeSession(responses=[roadmap_json])
        agent = ThinkingAgent(runtime)
        roadmaps = asyncio.run(
            agent.generate_roadmaps("Prove sum of first n odds = n^2", None, count=3)
        )
        assert len(roadmaps) >= 1
        assert "steps" in roadmaps[0]

    def test_work_step_with_verification(self):
        runtime = MockRuntimeSession(responses=[
            "The base case is trivial: 1 = 1^2.",
            (
                "OUTCOME: PROVED\n"
                "EXPLANATION: The proof establishes the exact stated step.\n"
                "DERIVED_CLAIM: NONE\n"
                "FALSE_CLAIM: NONE"
            ),
        ])
        agent = ThinkingAgent(runtime)
        result = asyncio.run(
            agent.work_step(
                "Prove sum of first n odds = n^2",
                "Step 1: Base case",
                "Show P(1): 1 = 1^2",
                1,
            )
        )
        assert result.step_index == 1
        assert result.status == "PROVED"
        assert result.verification_passed is True
        assert result.verification_outcome == "PROVED"

    def test_work_step_refuted_step_is_not_marked_proved(self):
        runtime = MockRuntimeSession(responses=[
            "Counterexample: the claim fails at n = 2.",
            (
                "OUTCOME: REFUTED_STEP\n"
                "EXPLANATION: The argument gives a counterexample, so the step is false.\n"
                "DERIVED_CLAIM: NONE\n"
                "FALSE_CLAIM: The claimed implication holds for every n."
            ),
        ])
        agent = ThinkingAgent(runtime)
        result = asyncio.run(
            agent.work_step(
                "Prove a false statement",
                "Step 1: prove the impossible claim",
                "Claim the implication holds for every n",
                1,
            )
        )
        assert result.status == "REFUTED_STEP"
        assert result.verification_passed is False
        assert result.false_claim == "The claimed implication holds for every n."
        assert "counterexample" in result.error_reason.lower()

    def test_generate_roadmaps_normalizes_macro_steps(self):
        roadmap_json = json.dumps([{
            "approach": "Split into structural chapters",
            "reasoning": "Natural decomposition",
            "macro_steps": [
                {
                    "description": "Derive constraints",
                    "deliverable": "",
                    "steps": ["Find necessary conditions", "Check boundary cases"]
                },
                {
                    "description": "Verify sufficiency",
                    "deliverable": "Sufficiency proof",
                    "steps": ["Prove each candidate works"]
                }
            ],
            "steps": [
                "Find necessary conditions",
                "Check boundary cases",
                "Prove each candidate works"
            ]
        }])
        runtime = MockRuntimeSession(responses=[roadmap_json])
        agent = ThinkingAgent(runtime)
        roadmaps = asyncio.run(
            agent.generate_roadmaps("Classify the solutions", None, count=1)
        )
        assert roadmaps[0]["macro_steps"][0]["deliverable"]
        assert roadmaps[0]["steps"] == [
            "Find necessary conditions",
            "Check boundary cases",
            "Prove each candidate works",
        ]

    def test_generate_roadmaps_splits_overloaded_step(self):
        roadmap_json = json.dumps([{
            "approach": "Do everything at once",
            "steps": ["Combine all remaining cases and finish by standard argument"],
            "reasoning": "Too coarse"
        }])
        runtime = MockRuntimeSession(responses=[
            roadmap_json,
            json.dumps([
                "Handle the remaining small cases",
                "Assemble the final contradiction",
            ]),
        ])
        agent = ThinkingAgent(runtime)
        roadmaps = asyncio.run(
            agent.generate_roadmaps("Finish the proof", None, count=1)
        )
        assert roadmaps[0]["steps"] == [
            "Handle the remaining small cases",
            "Assemble the final contradiction",
        ]

    def test_try_parse_updated_steps_index_dicts_passthrough(self):
        """Happy path: the LLM returns the requested list[dict] shape."""
        content = (
            "NEEDS_UPDATE: reasoning ...\n"
            '[{"index": 3, "description": "Prove lemma via grid bijection"},'
            ' {"index": 4, "description": "Apply total order"}]'
        )
        reference = [
            {"index": 3, "description": "old step 3"},
            {"index": 4, "description": "old step 4"},
        ]
        parsed = ThinkingAgent._try_parse_updated_steps(content, reference)
        assert parsed == [
            {"index": 3, "description": "Prove lemma via grid bijection"},
            {"index": 4, "description": "Apply total order"},
        ]

    def test_try_parse_updated_steps_bare_string_array(self):
        """Regression: the LLM returns list[str] instead of list[dict]
        (the exact shape that historically crashed Phase1 with
        ``AttributeError: 'str' object has no attribute 'get'``). The
        parser must align positionally with the reference-step indices
        and return list[dict]."""
        content = (
            "NEEDS_UPDATE. The remaining steps need restructuring.\n"
            '["Prove d_i is constant on each level",'
            ' "Apply the grid bijection to count L_i"]'
        )
        reference = [
            {"index": 5, "description": "derive the floor inequality"},
            {"index": 6, "description": "wrap up by counting"},
        ]
        parsed = ThinkingAgent._try_parse_updated_steps(content, reference)
        assert parsed == [
            {"index": 5, "description": "Prove d_i is constant on each level"},
            {"index": 6, "description": "Apply the grid bijection to count L_i"},
        ]
        # Every element must be a dict so the phase1.py `updated.get(...)`
        # loops cannot crash.
        assert all(isinstance(item, dict) for item in parsed)

    def test_try_parse_updated_steps_appends_new_indices(self):
        content = (
            "STATUS: NEEDS_EXTENSION\n"
            '[{"index": 5, "description": "Repair the dependency chain"},'
            ' {"description": "Prove the converse direction explicitly"}]'
        )
        reference = [
            {"index": 5, "description": "old step 5"},
        ]
        parsed = ThinkingAgent._try_parse_updated_steps(content, reference)
        assert parsed == [
            {"index": 5, "description": "Repair the dependency chain"},
            {"index": 6, "description": "Prove the converse direction explicitly"},
        ]

    def test_try_parse_updated_steps_junk_returns_none(self):
        """Non-JSON content must return None rather than raise."""
        assert ThinkingAgent._try_parse_updated_steps("ON_TRACK", None) is None
        assert ThinkingAgent._try_parse_updated_steps(
            "[not valid json", [{"index": 1, "description": "x"}]
        ) is None
        # Empty array => None (callers treat None as "no rewrite").
        assert ThinkingAgent._try_parse_updated_steps(
            "NEEDS_UPDATE: []", [{"index": 1, "description": "x"}]
        ) is None

    def test_assess_completeness_parses_missing_steps(self):
        runtime = MockRuntimeSession(responses=[
            (
                "STATUS: INCOMPLETE\n"
                'MISSING_OBLIGATIONS: ["sufficiency_direction", "final_target_link"]\n'
                'MISSING_STEPS: ["Prove the converse direction.", "Conclude the original theorem."]\n'
                "EXPLANATION: The roadmap only proved necessary conditions."
            )
        ])
        agent = ThinkingAgent(runtime)
        assessment = asyncio.run(
            agent.assess_completeness(
                "Prove A iff B",
                "Roadmap summary",
                [{"index": 1, "description": "Prove A implies B"}],
                ["sufficiency_direction: prove the sufficient / converse direction"],
            )
        )
        assert assessment.is_complete is False
        assert assessment.missing_obligations == [
            "sufficiency_direction",
            "final_target_link",
        ]
        assert assessment.missing_steps == [
            "Prove the converse direction.",
            "Conclude the original theorem.",
        ]

    def test_repair_proof_does_not_replay_large_context(self):
        runtime = MockRuntimeSession(responses=["Repaired proof"])
        agent = ThinkingAgent(runtime)
        agent.add_to_context(RuntimeMessage(role="user", content="old context"))
        repaired = asyncio.run(
            agent.repair_proof(
                "Problem",
                "Long proof text",
                ["gap 1"],
                "Reviewer reasoning",
            )
        )
        assert repaired == "Repaired proof"
        assert runtime.calls[0]["transcript"] == []

    # ------------------------------------------------------------------
    # Fix 5: strategic-divergence prompt in generate_roadmaps
    # ------------------------------------------------------------------

    def test_generate_roadmaps_injects_divergence_when_two_prior_attempts(self):
        """With 2 prior attempts, the prompt must carry the strong
        "STRATEGIC DIVERGENCE REQUIRED" instruction plus a listing of
        every prior approach and its failure reason. This is the
        load-bearing Fix 5 behaviour — the planner must SEE what was
        tried in order to avoid rephrasing it."""
        roadmap_json = json.dumps([{
            "approach": "Probabilistic / algebraic approach",
            "steps": ["Set up expectation", "Derive contradiction"],
            "reasoning": "Fundamentally different paradigm"
        }])
        runtime = MockRuntimeSession(responses=[roadmap_json])
        agent = ThinkingAgent(runtime)
        prior = [
            {
                "name": "Roadmap 1",
                "approach": "Explicit combinatorial construction",
                "failure_reason": "Review found gaps: positional template missing",
                "lesson": "Could not write formulas",
                "review_rejected": "true",
            },
            {
                "name": "Roadmap 2",
                "approach": "Explicit combinatorial construction v2",
                "failure_reason": "Review found gaps: positional template missing",
                "lesson": "Same issue as before",
                "review_rejected": "true",
            },
        ]
        asyncio.run(
            agent.generate_roadmaps(
                "Prove hard problem",
                memo_content="(MEMO)",
                count=1,
                prior_attempts=prior,
            )
        )
        # Inspect the prompt that was sent to the mock runtime.
        assert len(runtime.calls) == 1
        prompt = runtime.calls[0]["prompt"]
        assert "STRATEGIC DIVERGENCE REQUIRED" in prompt
        assert "2 previous roadmap attempt" in prompt
        # Both approaches must appear verbatim.
        assert "Explicit combinatorial construction" in prompt
        assert "Explicit combinatorial construction v2" in prompt
        # And the [REVIEW-REJECTED] tag for both.
        assert prompt.count("[REVIEW-REJECTED]") == 2
        # Failure reasons must appear so the planner can recognise the
        # shared failure mode.
        assert "positional template missing" in prompt
        # At least one alternative paradigm must be listed.
        assert "Probabilistic" in prompt or "matching / flow theorems" in prompt

    def test_generate_roadmaps_no_divergence_when_one_attempt(self):
        """A single prior attempt is not enough signal to declare a
        paradigm dead — the divergence block must stay quiet."""
        roadmap_json = json.dumps([{
            "approach": "Try again with refinement",
            "steps": ["Step A", "Step B"],
            "reasoning": "Refined version"
        }])
        runtime = MockRuntimeSession(responses=[roadmap_json])
        agent = ThinkingAgent(runtime)
        prior = [
            {
                "name": "Roadmap 1",
                "approach": "First try",
                "failure_reason": "Stagnation detected",
                "lesson": "Refine step 3",
                "review_rejected": "false",
            },
        ]
        asyncio.run(
            agent.generate_roadmaps(
                "Problem",
                memo_content="(MEMO)",
                count=1,
                prior_attempts=prior,
            )
        )
        prompt = runtime.calls[0]["prompt"]
        assert "STRATEGIC DIVERGENCE REQUIRED" not in prompt

    def test_generate_roadmaps_no_divergence_when_zero_attempts(self):
        """First-attempt invocation must not carry the divergence block
        at all — nothing to diverge from yet."""
        roadmap_json = json.dumps([{
            "approach": "Standard approach",
            "steps": ["Step A"],
            "reasoning": "First try"
        }])
        runtime = MockRuntimeSession(responses=[roadmap_json])
        agent = ThinkingAgent(runtime)
        asyncio.run(
            agent.generate_roadmaps(
                "Problem",
                memo_content=None,
                count=1,
                prior_attempts=None,
            )
        )
        prompt = runtime.calls[0]["prompt"]
        assert "STRATEGIC DIVERGENCE REQUIRED" not in prompt

    def test_generate_roadmaps_prompt_mentions_iff_and_existence_guards(self):
        roadmap_json = json.dumps([{
            "approach": "Forward then converse",
            "steps": ["Prove A implies B", "Construct witness", "Prove converse"],
            "reasoning": "Cover both directions and the witness",
        }])
        runtime = MockRuntimeSession(responses=[roadmap_json])
        agent = ThinkingAgent(runtime)
        asyncio.run(
            agent.generate_roadmaps(
                "Prove that A if and only if there exists an object X with property P",
                None,
                count=1,
            )
        )
        prompt = runtime.calls[0]["prompt"]
        assert "If the problem states an equivalence" in prompt
        assert "If the theorem requires existence or construction" in prompt

    def test_format_divergence_instruction_lists_approaches_and_tags(self):
        """Direct unit test on the formatting helper — the rendered
        string must contain each approach, its failure reason, its
        lesson, and a [REVIEW-REJECTED] marker for the rejected entry."""
        prior = [
            {
                "approach": "Induction on n",
                "failure_reason": "Stagnation",
                "lesson": "Induction does not carry the hard case",
                "review_rejected": "false",
            },
            {
                "approach": "Explicit construction",
                "failure_reason": "Review found gaps",
                "lesson": "Pivot paradigm",
                "review_rejected": "true",
            },
        ]
        text = ThinkingAgent._format_divergence_instruction(prior)
        assert "STRATEGIC DIVERGENCE REQUIRED" in text
        assert "Induction on n" in text
        assert "Explicit construction" in text
        assert "[REVIEW-REJECTED]" in text
        # Exactly one of the two entries is marked.
        assert text.count("[REVIEW-REJECTED]") == 1
        assert "Stagnation" in text
        assert "Review found gaps" in text
        assert "Pivot paradigm" in text

    def test_try_parse_updated_steps_mixed_array_drops_bad_items(self):
        """Nulls and numbers inside the array must be silently skipped,
        not coerced into a malformed dict."""
        content = (
            'NEEDS_UPDATE\n'
            '[{"index": 2, "description": "keep this"}, null, 42,'
            ' "positional string maps to ref[3]"]'
        )
        reference = [
            {"index": 1, "description": "a"},
            {"index": 2, "description": "b"},
            {"index": 3, "description": "c"},
            {"index": 4, "description": "d"},
        ]
        parsed = ThinkingAgent._try_parse_updated_steps(content, reference)
        assert parsed == [
            {"index": 2, "description": "keep this"},
            {"index": 4, "description": "positional string maps to ref[3]"},
        ]
