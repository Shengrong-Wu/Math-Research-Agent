import re

from math_agent.agents.prompt_loader import load_prompt_bundle, load_prompt_section, render_prompt_section


REQUIRED_SECTIONS = {
    "system_prompt",
    "roadmap_generation",
    "divergence_instruction",
    "split_overloaded_step",
    "regenerate_macro_step",
    "step_prove",
    "step_verify",
    "verify_proved_step",
    "formalize_statement",
    "formalize_step_sketch",
    "repair_proof",
    "diagnose_step_failure",
    "reevaluate_roadmap",
    "reevaluate_after_failure",
    "completeness_check",
}


def _assert_no_unresolved_placeholders(text: str) -> None:
    assert re.search(r"\{[a-zA-Z_][^}]*\}", text) is None


def test_thinking_bundle_contains_expected_sections():
    bundle = load_prompt_bundle("thinking_bundle")
    assert REQUIRED_SECTIONS.issubset(bundle.keys())


def test_system_prompt_loads():
    assert "Thinking Agent" in load_prompt_section("thinking_bundle", "system_prompt")


def test_thinking_prompt_sections_render_with_current_kwargs():
    rendered = {
        "roadmap_generation": render_prompt_section(
            "thinking_bundle",
            "roadmap_generation",
            problem_question="Prove a theorem.",
            memo_block="",
            divergence_block="",
            count=3,
            n_min=5,
            n_max=15,
        ),
        "divergence_instruction": render_prompt_section(
            "thinking_bundle",
            "divergence_instruction",
            prior_attempt_count=2,
            previous_attempts="  1. Approach: Old route\n     Failed because: Gap\n",
        ),
        "split_overloaded_step": render_prompt_section(
            "thinking_bundle",
            "split_overloaded_step",
            problem_question="Problem text",
            step_description="Combine all remaining cases.",
        ),
        "regenerate_macro_step": render_prompt_section(
            "thinking_bundle",
            "regenerate_macro_step",
            problem_question="Problem text",
            macro_description="Macro",
            macro_deliverable="Deliverable",
            completed_macro_summaries="- one",
            failed_sub_steps="- two",
        ),
        "step_prove": render_prompt_section(
            "thinking_bundle",
            "step_prove",
            problem_question="Problem text",
            roadmap_summary="Roadmap",
            context_block="",
            step_number=1,
            step_description="Prove X",
        ),
        "step_verify": render_prompt_section(
            "thinking_bundle",
            "step_verify",
            problem_question="Problem text",
            roadmap_summary="Roadmap",
            step_number=1,
            step_description="Prove X",
            proof_detail="Proof",
        ),
        "verify_proved_step": render_prompt_section(
            "thinking_bundle",
            "verify_proved_step",
            problem_question="Problem text",
            step_description="Prove X",
            step_index=1,
            proof_detail="Proof",
        ),
        "formalize_statement": render_prompt_section(
            "thinking_bundle",
            "formalize_statement",
            problem_question="Problem text",
            approach="Approach",
        ),
        "formalize_step_sketch": render_prompt_section(
            "thinking_bundle",
            "formalize_step_sketch",
            problem_question="Problem text",
            step_description="Step",
            proved_propositions_text="- lemma",
        ),
        "repair_proof": render_prompt_section(
            "thinking_bundle",
            "repair_proof",
            problem_question="Problem text",
            complete_proof="Proof",
            gaps_text="  - gap",
            reviewer_reasoning="Reasoning",
        ),
        "diagnose_step_failure": render_prompt_section(
            "thinking_bundle",
            "diagnose_step_failure",
            problem_question="Problem text",
            step_description="Step",
            step_index=2,
            error_count=3,
            errors_text="  Attempt 1: bad",
        ),
        "reevaluate_roadmap": render_prompt_section(
            "thinking_bundle",
            "reevaluate_roadmap",
            problem_question="Problem text",
            roadmap_summary="Roadmap",
            completed_steps_json="[]",
            remaining_steps_json="[]",
            required_obligations_json="[]",
        ),
        "reevaluate_after_failure": render_prompt_section(
            "thinking_bundle",
            "reevaluate_after_failure",
            problem_question="Problem text",
            roadmap_summary="Roadmap",
            completed_steps_json="[]",
            failed_step_json="{}",
            remaining_steps_json="[]",
        ),
        "completeness_check": render_prompt_section(
            "thinking_bundle",
            "completeness_check",
            problem_question="Problem text",
            roadmap_summary="Roadmap",
            proved_steps_json="[]",
            required_obligations_json="[]",
        ),
    }

    for text in rendered.values():
        assert text.strip()
        _assert_no_unresolved_placeholders(text)
