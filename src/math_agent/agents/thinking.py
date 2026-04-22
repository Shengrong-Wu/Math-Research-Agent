"""The Thinking Agent -- main proof reasoning worker.

Responsible for generating proof roadmaps, working through individual proof
steps, self-verifying results, and re-evaluating the roadmap as work progresses.
"""

from __future__ import annotations

import copy
import json
import re

from math_agent.config import Hyperparameters

from .base import BaseAgent, CompletenessCheck, RoadmapEvaluation, StepResult
from .prompt_loader import load_prompt_section, render_prompt_section

_PROMPT_BUNDLE = "thinking_bundle"
_SYSTEM_PROMPT = load_prompt_section(_PROMPT_BUNDLE, "system_prompt").strip()


class ThinkingAgent(BaseAgent):
    """Main proof reasoning worker.

    Generates proof roadmaps, works through proof steps one at a time,
    self-verifies each step, and re-evaluates the overall roadmap after
    each completed step.
    """

    def __init__(self, runtime, hyper: Hyperparameters | None = None):
        super().__init__(runtime)
        self.hyper = hyper or Hyperparameters()

    @staticmethod
    def _render_prompt(section: str, **kwargs: object) -> str:
        return render_prompt_section(_PROMPT_BUNDLE, section, **kwargs)

    async def generate_roadmaps(
        self,
        problem_question: str,
        memo_content: str | None = None,
        count: int = 3,
        prior_attempts: list[dict[str, str]] | None = None,
        extra_metadata: dict | None = None,
    ) -> list[dict]:
        """Generate proof roadmaps for the given problem.

        Each roadmap is a dict with keys:
            - approach (str): high-level description of the proof strategy
            - steps (list[str]): ordered list of step descriptions
            - reasoning (str): why this approach is promising

        If *memo_content* is provided (i.e. this is a subsequent attempt),
        exactly one roadmap is generated, informed by the MEMO from the
        previous attempt.

        Args:
            problem_question: The mathematical problem statement.
            memo_content: Optional MEMO from a prior attempt.
            count: Number of roadmaps to generate (ignored when memo is given).
            prior_attempts: Optional list of summary dicts (one per
                previously abandoned roadmap) in the shape returned by
                ``Memo.prior_attempts_summary``. When 2+ attempts are
                present, a strong "strategic divergence" instruction is
                injected into the prompt so the planner does not rephrase
                a strategy that already failed.

        Returns:
            A list of roadmap dicts.
        """
        if memo_content is not None:
            count = 1

        memo_block = ""
        if memo_content:
            memo_block = (
                "MEMO from a previous attempt (use this to improve your strategy):\n"
                f"{memo_content}\n\n"
            )
        # Fix 5: strategic divergence pressure when multiple attempts
        # have already been abandoned. The production run showed the
        # planner rephrasing the same "explicit combinatorial construction"
        # strategy three times in a row after review rejections, dying at
        # the structurally equivalent "define the positional template"
        # step every time. Injecting this instruction forces a paradigm
        # change rather than a cosmetic rewording.
        divergence_block = ""
        if prior_attempts and len(prior_attempts) >= 2:
            divergence_block = self._format_divergence_instruction(prior_attempts)
        user_content = self._render_prompt(
            "roadmap_generation",
            problem_question=problem_question,
            memo_block=memo_block,
            divergence_block=divergence_block,
            count=count,
            n_min=self.hyper.n_min,
            n_max=self.hyper.n_max,
        )
        extra = dict(extra_metadata or {})
        doc_counts = {
            "problem_question": len(problem_question),
            "memo_content": len(memo_content or ""),
            "divergence_block": len(divergence_block),
        }
        doc_counts.update(extra.pop("document_char_counts", {}))

        response = await self._request_text(
            user_content,
            system_prompt=_SYSTEM_PROMPT,
            include_context=False,
            record_history=False,
            use_native_session=False,
            metadata={
                "callsite": "thinking.generate_roadmaps",
                "document_char_counts": doc_counts,
                **extra,
            },
        )

        roadmaps = self._normalize_roadmaps(self._parse_roadmaps(response.content))
        refined: list[dict] = []
        for roadmap in roadmaps:
            refined.append(
                await self._refine_overloaded_steps(problem_question, roadmap)
            )
        return refined

    @staticmethod
    def _format_divergence_instruction(
        prior_attempts: list[dict[str, str]],
    ) -> str:
        """Render the strategic-divergence block for ``generate_roadmaps``.

        Lists every prior roadmap's approach and failure reason, then
        demands a fundamentally different strategic paradigm. Kept as a
        module-level helper so tests can assert on the exact prompt text
        without having to mock the LLM call.
        """
        lines: list[str] = []
        for i, attempt in enumerate(prior_attempts, 1):
            approach = (attempt.get("approach") or "(no approach recorded)").strip()
            failure = (attempt.get("failure_reason") or "").strip()
            lesson = (attempt.get("lesson") or "").strip()
            review_tag = (
                " [REVIEW-REJECTED]"
                if str(attempt.get("review_rejected", "")).lower() == "true"
                else ""
            )
            lines.append(f"  {i}. Approach{review_tag}: {approach}\n")
            if failure:
                lines.append(f"     Failed because: {failure}\n")
            if lesson:
                lines.append(f"     Lesson: {lesson}\n")
        return ThinkingAgent._render_prompt(
            "divergence_instruction",
            prior_attempt_count=len(prior_attempts),
            previous_attempts="".join(lines),
        )

    async def split_overloaded_step(
        self,
        problem_question: str,
        step_description: str,
    ) -> list[str]:
        """Split an overloaded step into more focused sub-steps."""
        content = self._render_prompt(
            "split_overloaded_step",
            problem_question=problem_question,
            step_description=step_description,
        )
        response = await self._request_text(
            content,
            system_prompt=_SYSTEM_PROMPT,
            include_context=False,
            record_history=False,
            use_native_session=False,
            metadata={
                "callsite": "thinking.split_overloaded_step",
                "document_char_counts": {
                    "problem_question": len(problem_question),
                    "step_description": len(step_description),
                },
            },
        )
        parsed = self._parse_string_array(response.content)
        return parsed or [step_description]

    async def repair_step_with_feedback(
        self,
        problem_question: str,
        roadmap_summary: str,
        step_description: str,
        step_index: int,
        feedback: str,
    ) -> StepResult:
        """Retry a step with explicit repair feedback."""
        return await self.work_step(
            problem_question,
            roadmap_summary,
            step_description,
            step_index,
            context_notes=f"Repair this step using the following feedback:\n{feedback}",
        )

    async def regenerate_macro_step(
        self,
        problem_question: str,
        macro_description: str,
        macro_deliverable: str,
        completed_macro_summaries: list[str],
        failed_sub_steps: list[str],
    ) -> list[str]:
        """Regenerate only the sub-steps for a failed macro-step."""
        completed = "\n".join(f"- {item}" for item in completed_macro_summaries) or "(none)"
        failed = "\n".join(f"- {item}" for item in failed_sub_steps) or "(none)"
        content = self._render_prompt(
            "regenerate_macro_step",
            problem_question=problem_question,
            macro_description=macro_description,
            macro_deliverable=macro_deliverable,
            completed_macro_summaries=completed,
            failed_sub_steps=failed,
        )
        response = await self._request_text(
            content,
            system_prompt=_SYSTEM_PROMPT,
            include_context=False,
            record_history=False,
            use_native_session=False,
            metadata={
                "callsite": "thinking.regenerate_macro_step",
                "document_char_counts": {
                    "problem_question": len(problem_question),
                    "macro_description": len(macro_description),
                    "failed_sub_steps": len(failed),
                },
            },
        )
        parsed = self._parse_string_array(response.content)
        return parsed or [macro_description]

    async def work_step(
        self,
        problem_question: str,
        roadmap_summary: str,
        step_description: str,
        step_index: int,
        context_notes: str = "",
        extra_metadata: dict | None = None,
    ) -> StepResult:
        """Work through a single proof step.

        The agent first reasons about and writes the proof for the step,
        then performs a self-check asking whether the proof is correct.

        Args:
            problem_question: The original problem statement.
            roadmap_summary: Summary of the overall proof roadmap.
            step_description: Description of the specific step to prove.
            step_index: Zero-based index of this step in the roadmap.
            context_notes: Additional context (e.g. results of prior steps).

        Returns:
            A StepResult capturing the outcome and self-verification.
        """
        # --- Phase 1: prove the step ---
        context_block = ""
        if context_notes:
            context_block = f"Context from previous steps:\n{context_notes}\n\n"
        prove_content = self._render_prompt(
            "step_prove",
            problem_question=problem_question,
            roadmap_summary=roadmap_summary,
            context_block=context_block,
            step_number=step_index,
            step_description=step_description,
        )
        extra = dict(extra_metadata or {})
        prove_doc_counts = {
            "problem_question": len(problem_question),
            "roadmap_summary": len(roadmap_summary),
            "context_notes": len(context_notes),
            "step_description": len(step_description),
        }
        prove_doc_counts.update(extra.pop("document_char_counts", {}))

        prove_response = await self._request_text(
            prove_content,
            system_prompt=_SYSTEM_PROMPT,
            context_window=4,
            metadata={
                "callsite": "thinking.work_step.prove",
                "document_char_counts": prove_doc_counts,
                **extra,
            },
        )

        # --- Stage 2: self-verify ---
        verify_content = self._render_prompt(
            "step_verify",
            problem_question=problem_question,
            roadmap_summary=roadmap_summary,
            step_number=step_index,
            step_description=step_description,
            proof_detail=prove_response.content,
        )

        verify_response = await self._request_text(
            verify_content,
            system_prompt=_SYSTEM_PROMPT,
            include_context=False,
            record_history=False,
            use_native_session=False,
            metadata={
                "callsite": "thinking.work_step.verify",
                "document_char_counts": {
                    "problem_question": len(problem_question),
                    "roadmap_summary": len(roadmap_summary),
                    "step_description": len(step_description),
                    "proof_detail": len(prove_response.content),
                },
                **{
                    key: value
                    for key, value in (extra_metadata or {}).items()
                    if key != "document_char_counts"
                },
            },
        )

        (
            verification_outcome,
            verification_notes,
            derived_claim,
            false_claim,
        ) = self._parse_step_verification(verify_response.content)

        verification_passed = verification_outcome == "PROVED"
        status = verification_outcome
        error_reason = "" if verification_passed else (
            verification_notes or verify_response.content
        )

        return StepResult(
            step_index=step_index,
            status=status,
            reasoning=prove_response.content,
            proof_detail=prove_response.content,
            verification_passed=verification_passed,
            verification_outcome=verification_outcome,
            verification_notes=verification_notes,
            derived_claim=derived_claim,
            false_claim=false_claim,
            error_reason=error_reason,
        )

    async def verify_proved_step(
        self,
        problem_question: str,
        step_description: str,
        step_index: int,
        proof_detail: str,
    ) -> bool:
        """Verify a previously proved step by reviewing its recorded proof.

        Used during resume to check whether steps proved in a prior run
        are actually correct before skipping them.

        Args:
            problem_question: The original problem statement.
            step_description: Description of the step.
            step_index: 1-based index of the step.
            proof_detail: The full proof text from NOTES.

        Returns:
            True if the proof is verified correct, False otherwise.
        """
        verify_content = self._render_prompt(
            "verify_proved_step",
            problem_question=problem_question,
            step_description=step_description,
            step_index=step_index,
            proof_detail=proof_detail,
        )

        response = await self._request_text(
            verify_content,
            system_prompt=_SYSTEM_PROMPT,
            include_context=False,
            record_history=False,
            use_native_session=False,
            metadata={
                "callsite": "thinking.verify_proved_step",
                "document_char_counts": {
                    "problem_question": len(problem_question),
                    "step_description": len(step_description),
                    "proof_detail": len(proof_detail),
                },
            },
        )

        return "VERIFIED" in response.content.upper()

    async def formalize_statement(
        self,
        problem_question: str,
        approach: str,
    ) -> str:
        """Generate a Lean 4 theorem statement for the problem.

        Returns the Lean code (imports + theorem statement with sorry body),
        or empty string if generation fails.
        """
        content = self._render_prompt(
            "formalize_statement",
            problem_question=problem_question,
            approach=approach,
        )
        response = await self._request_text(
            content,
            system_prompt=_SYSTEM_PROMPT,
            include_context=False,
            record_history=False,
            use_native_session=False,
            metadata={
                "callsite": "thinking.formalize_statement",
                "document_char_counts": {
                    "problem_question": len(problem_question),
                    "approach": len(approach),
                },
            },
        )

        # Extract code block if wrapped in markdown fences
        code = response.content.strip()
        if "```lean" in code:
            import re
            m = re.search(r"```lean\n(.*?)```", code, re.DOTALL)
            if m:
                code = m.group(1).strip()
        elif "```" in code:
            import re
            m = re.search(r"```\n(.*?)```", code, re.DOTALL)
            if m:
                code = m.group(1).strip()
        return code

    async def formalize_step_sketch(
        self,
        problem_question: str,
        step_description: str,
        proved_propositions: list[str],
    ) -> str:
        """Generate a Lean 4 lemma sketch for a proved step.

        Returns the Lean code (imports + lemma statement + sorry body),
        or empty string if generation fails.
        """
        props_text = "\n".join(f"- {p}" for p in proved_propositions) if proved_propositions else "(none)"
        content = self._render_prompt(
            "formalize_step_sketch",
            problem_question=problem_question,
            step_description=step_description,
            proved_propositions_text=props_text,
        )
        response = await self._request_text(
            content,
            system_prompt=_SYSTEM_PROMPT,
            include_context=False,
            record_history=False,
            use_native_session=False,
            metadata={
                "callsite": "thinking.formalize_step_sketch",
                "document_char_counts": {
                    "problem_question": len(problem_question),
                    "step_description": len(step_description),
                    "proved_propositions_text": len(props_text),
                },
            },
        )

        code = response.content.strip()
        if "```lean" in code:
            import re
            m = re.search(r"```lean\n(.*?)```", code, re.DOTALL)
            if m:
                code = m.group(1).strip()
        elif "```" in code:
            import re
            m = re.search(r"```\n(.*?)```", code, re.DOTALL)
            if m:
                code = m.group(1).strip()
        return code

    async def repair_proof(
        self,
        problem_question: str,
        complete_proof: str,
        gaps: list[str],
        reviewer_reasoning: str,
    ) -> str:
        """Repair specific gaps identified by the reviewer.

        Instead of starting a new roadmap from scratch, this method takes
        the existing (mostly-correct) proof and the reviewer's specific
        feedback, and asks the agent to fix only the broken parts.

        Args:
            problem_question: The original problem statement.
            complete_proof: The current complete proof text.
            gaps: List of specific gaps identified by the reviewer.
            reviewer_reasoning: The reviewer's full reasoning.

        Returns:
            The repaired complete proof text.
        """
        gaps_text = "\n".join(f"  - {g}" for g in gaps)

        repair_content = self._render_prompt(
            "repair_proof",
            problem_question=problem_question,
            complete_proof=complete_proof,
            gaps_text=gaps_text,
            reviewer_reasoning=reviewer_reasoning,
        )

        response = await self._request_text(
            repair_content,
            system_prompt=_SYSTEM_PROMPT,
            include_context=False,
            record_history=False,
            use_native_session=False,
            metadata={
                "callsite": "thinking.repair_proof",
                "document_char_counts": {
                    "problem_question": len(problem_question),
                    "complete_proof": len(complete_proof),
                    "gaps_text": len(gaps_text),
                },
            },
        )

        return response.content

    async def diagnose_step_failure(
        self,
        problem_question: str,
        step_description: str,
        step_index: int,
        error_reasons: list[str],
    ) -> dict:
        """Diagnose WHY a step failed after multiple attempts.

        Categorizes the failure as one of:
        - FALSE_PROPOSITION: the step's claim is actually false
        - LOGICAL_GAP: the claim may be true but the proof has a gap
        - INSUFFICIENT_TECHNIQUE: the claim is likely true but we lack
          the technique to prove it within this approach
        - UNCLEAR: cannot determine the cause

        Args:
            problem_question: The original problem statement.
            step_description: Description of the failed step.
            step_index: Index of the failed step.
            error_reasons: List of error reasons from each attempt.

        Returns:
            Dict with keys: diagnosis, explanation, false_claim (if applicable).
        """
        errors_text = "\n".join(
            f"  Attempt {i+1}: {reason[:300]}"
            for i, reason in enumerate(error_reasons)
        )

        diagnose_content = self._render_prompt(
            "diagnose_step_failure",
            problem_question=problem_question,
            step_description=step_description,
            step_index=step_index,
            error_count=len(error_reasons),
            errors_text=errors_text,
        )

        response = await self._request_text(
            diagnose_content,
            system_prompt=_SYSTEM_PROMPT,
            metadata={
                "callsite": "thinking.diagnose_step_failure",
                "document_char_counts": {
                    "problem_question": len(problem_question),
                    "step_description": len(step_description),
                    "errors_text": len(errors_text),
                },
            },
        )

        # Parse structured response
        content = response.content
        diagnosis = "UNCLEAR"
        explanation = content
        false_claim = ""

        for valid in ("FALSE_PROPOSITION", "LOGICAL_GAP",
                       "INSUFFICIENT_TECHNIQUE", "UNCLEAR"):
            if valid in content.upper():
                diagnosis = valid
                break

        # Extract EXPLANATION line
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.upper().startswith("EXPLANATION:"):
                explanation = stripped[len("EXPLANATION:"):].strip()
            elif stripped.upper().startswith("FALSE_CLAIM:"):
                claim = stripped[len("FALSE_CLAIM:"):].strip()
                if claim.upper() != "NONE":
                    false_claim = claim

        return {
            "diagnosis": diagnosis,
            "explanation": explanation,
            "false_claim": false_claim,
        }

    async def re_evaluate_roadmap(
        self,
        problem_question: str,
        roadmap_summary: str,
        completed_steps: list[dict],
        remaining_steps: list[dict],
        required_obligations: list[str] | None = None,
    ) -> RoadmapEvaluation:
        """Re-evaluate the roadmap after a step has been proved.

        Checks whether the remaining steps still make sense given what has
        been proved so far, and proposes modifications if needed.

        Args:
            problem_question: The original problem statement.
            roadmap_summary: Summary of the overall proof roadmap.
            completed_steps: List of dicts describing completed steps.
            remaining_steps: List of dicts describing remaining steps.

        Returns:
            A RoadmapEvaluation with on_track flag and optional updates.
        """
        eval_content = self._render_prompt(
            "reevaluate_roadmap",
            problem_question=problem_question,
            roadmap_summary=roadmap_summary,
            completed_steps_json=json.dumps(completed_steps, indent=2),
            remaining_steps_json=json.dumps(remaining_steps, indent=2),
            required_obligations_json=json.dumps(
                required_obligations or [],
                indent=2,
            ),
        )

        response = await self._request_text(
            eval_content,
            system_prompt=_SYSTEM_PROMPT,
            include_context=False,
            record_history=False,
            use_native_session=False,
            metadata={
                "callsite": "thinking.re_evaluate_roadmap",
                "document_char_counts": {
                    "roadmap_summary": len(roadmap_summary),
                    "completed_steps_json": len(json.dumps(completed_steps, indent=2)),
                    "remaining_steps_json": len(json.dumps(remaining_steps, indent=2)),
                    "required_obligations_json": len(
                        json.dumps(required_obligations or [], indent=2)
                    ),
                },
            },
        )

        status_text = self._extract_labeled_value(response.content, "STATUS")
        normalized_status = (status_text or response.content).upper()
        on_track = "ON_TRACK" in normalized_status
        needs_extension = "NEEDS_EXTENSION" in normalized_status
        missing_obligations = self._extract_string_array_after_label(
            response.content,
            "MISSING_OBLIGATIONS",
        )
        updated_steps = None
        if not on_track:
            updated_steps = self._try_parse_updated_steps(
                response.content, remaining_steps
            )

        return RoadmapEvaluation(
            on_track=on_track,
            updated_steps=updated_steps,
            reasoning=response.content,
            needs_extension=needs_extension,
            missing_obligations=missing_obligations,
        )

    async def re_evaluate_after_failure(
        self,
        problem_question: str,
        roadmap_summary: str,
        completed_steps: list[dict],
        failed_step: dict,
        remaining_steps: list[dict],
    ) -> RoadmapEvaluation:
        """Re-evaluate the roadmap after a step has FAILED.

        Determines whether the remaining steps are still viable without
        the failed step, or whether the roadmap should be abandoned.

        Args:
            problem_question: The original problem statement.
            roadmap_summary: Summary of the overall proof roadmap.
            completed_steps: Steps that were proved.
            failed_step: The step that failed (dict with index + description).
            remaining_steps: Steps not yet attempted.

        Returns:
            A RoadmapEvaluation. If should_abandon is True, the roadmap
            should be abandoned and a new one generated.
        """
        eval_content = self._render_prompt(
            "reevaluate_after_failure",
            problem_question=problem_question,
            roadmap_summary=roadmap_summary,
            completed_steps_json=json.dumps(completed_steps, indent=2),
            failed_step_json=json.dumps(failed_step, indent=2),
            remaining_steps_json=json.dumps(remaining_steps, indent=2),
        )

        response = await self._request_text(
            eval_content,
            system_prompt=_SYSTEM_PROMPT,
            include_context=False,
            record_history=False,
            use_native_session=False,
            metadata={
                "callsite": "thinking.re_evaluate_after_failure",
                "document_char_counts": {
                    "roadmap_summary": len(roadmap_summary),
                    "completed_steps_json": len(json.dumps(completed_steps, indent=2)),
                    "failed_step_json": len(json.dumps(failed_step, indent=2)),
                    "remaining_steps_json": len(json.dumps(remaining_steps, indent=2)),
                },
            },
        )

        content_upper = response.content.upper()
        should_abandon = "ABANDON" in content_upper
        on_track = False  # a step failed, so we're never "on track"
        updated_steps = None

        if not should_abandon:
            updated_steps = self._try_parse_updated_steps(
                response.content, remaining_steps
            )

        return RoadmapEvaluation(
            on_track=on_track,
            updated_steps=updated_steps,
            reasoning=response.content,
            should_abandon=should_abandon,
        )

    async def assess_completeness(
        self,
        problem_question: str,
        roadmap_summary: str,
        proved_steps: list[dict],
        required_obligations: list[str] | None = None,
    ) -> CompletenessCheck:
        """Check whether the proved steps already cover the full theorem."""
        obligations = required_obligations or []
        proved_steps_json = json.dumps(proved_steps, indent=2)
        obligations_json = json.dumps(obligations, indent=2)
        content = self._render_prompt(
            "completeness_check",
            problem_question=problem_question,
            roadmap_summary=roadmap_summary,
            proved_steps_json=proved_steps_json,
            required_obligations_json=obligations_json,
        )
        response = await self._request_text(
            content,
            system_prompt=_SYSTEM_PROMPT,
            include_context=False,
            record_history=False,
            use_native_session=False,
            metadata={
                "callsite": "thinking.assess_completeness",
                "document_char_counts": {
                    "problem_question": len(problem_question),
                    "roadmap_summary": len(roadmap_summary),
                    "proved_steps_json": len(proved_steps_json),
                    "required_obligations_json": len(obligations_json),
                },
            },
        )

        status_text = self._extract_labeled_value(response.content, "STATUS")
        normalized_status = (status_text or response.content).upper()
        is_complete = "COMPLETE" in normalized_status and "INCOMPLETE" not in normalized_status
        return CompletenessCheck(
            is_complete=is_complete,
            reasoning=response.content,
            missing_obligations=self._extract_string_array_after_label(
                response.content,
                "MISSING_OBLIGATIONS",
            ),
            missing_steps=self._extract_string_array_after_label(
                response.content,
                "MISSING_STEPS",
            ),
        )

    def fork(self) -> ThinkingAgent:
        """Create a copy with the same client and a deep copy of the context."""
        new_agent = ThinkingAgent(
            self.runtime.fork(
                role=self.runtime.role,
                root_dir=self.runtime.root_dir,
                workspace=self.runtime.workspace,
            ),
            hyper=self.hyper,
        )
        new_agent._context = copy.deepcopy(self._context)
        return new_agent

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_labeled_value(content: str, label: str) -> str:
        prefix = f"{label.strip().upper()}:"
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith(prefix):
                return stripped.split(":", 1)[1].strip()
        return ""

    @staticmethod
    def _extract_string_array_after_label(content: str, label: str) -> list[str]:
        marker = f"{label.strip().upper()}:"
        upper = content.upper()
        idx = upper.find(marker)
        if idx == -1:
            return []
        start = content.find("[", idx)
        if start == -1:
            return []

        depth = 0
        in_string = False
        escape_next = False
        end = -1
        for pos in range(start, len(content)):
            ch = content[pos]
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = pos
                    break
        if end == -1:
            return []

        try:
            parsed = json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item).strip() for item in parsed if str(item).strip()]

    @classmethod
    def _parse_step_verification(
        cls,
        content: str,
    ) -> tuple[str, str, str, str]:
        outcome = cls._extract_labeled_value(content, "OUTCOME").upper()
        if outcome not in {
            "PROVED",
            "REFUTED_STEP",
            "PROVED_DIFFERENT_CLAIM",
            "FAILED",
        }:
            upper = content.upper()
            if "REFUTED_STEP" in upper:
                outcome = "REFUTED_STEP"
            elif "PROVED_DIFFERENT_CLAIM" in upper:
                outcome = "PROVED_DIFFERENT_CLAIM"
            elif "PROVED" in upper or "VERIFIED" in upper:
                outcome = "PROVED"
            else:
                outcome = "FAILED"
        explanation = cls._extract_labeled_value(content, "EXPLANATION") or content.strip()
        derived_claim = cls._extract_labeled_value(content, "DERIVED_CLAIM")
        false_claim = cls._extract_labeled_value(content, "FALSE_CLAIM")
        if derived_claim.upper() == "NONE":
            derived_claim = ""
        if false_claim.upper() == "NONE":
            false_claim = ""
        return outcome, explanation, derived_claim, false_claim

    @staticmethod
    def _parse_roadmaps(content: str) -> list[dict]:
        """Best-effort parse of JSON roadmaps from LLM output."""
        import re

        text = content.strip()

        # Strip markdown code fences (```json ... ``` or ``` ... ```)
        text = re.sub(r"```(?:json)?\s*\n?", "", text).strip()

        # --- Try 1: JSON array of roadmap objects ---
        # Try array FIRST because LLM usually returns [{"approach":...}, ...]
        arr_start = text.find("[")
        arr_end = text.rfind("]")
        if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
            try:
                parsed = json.loads(text[arr_start : arr_end + 1])
                if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        # --- Try 2: single JSON object ---
        # Use a balanced-brace approach to find the first complete object
        obj_start = text.find("{")
        if obj_start != -1:
            depth = 0
            obj_end = -1
            in_string = False
            escape_next = False
            for i in range(obj_start, len(text)):
                ch = text[i]
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\\":
                    escape_next = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        obj_end = i
                        break

            if obj_end != -1:
                try:
                    obj = json.loads(text[obj_start : obj_end + 1])
                    if isinstance(obj, dict) and ("steps" in obj or "approach" in obj):
                        return [obj]
                except json.JSONDecodeError:
                    pass

        # --- Try 3: multiple JSON objects separated by whitespace ---
        # Some LLMs return objects without an enclosing array
        objects = []
        for match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text):
            try:
                obj = json.loads(match.group())
                if isinstance(obj, dict) and ("steps" in obj or "approach" in obj):
                    objects.append(obj)
            except json.JSONDecodeError:
                continue
        if objects:
            return objects

        # --- Fallback: treat each line as a step ---
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        steps = []
        for line in lines:
            # Strip common list prefixes like "1.", "- ", "Step 1:"
            clean = re.sub(r"^(?:\d+[\.\)]\s*|[-*]\s*|Step\s+\d+:\s*)", "", line)
            # Skip lines that look like JSON syntax fragments
            if clean and clean not in ("[", "]", "{", "}", ",") and not clean.startswith('"approach"') and not clean.startswith('"steps"') and not clean.startswith('"reasoning"'):
                steps.append(clean.strip('"').rstrip(","))
        if not steps:
            steps = [text[:300]]

        return [
            {
                "approach": steps[0] if steps else "Generated roadmap",
                "steps": steps[:10],
                "reasoning": "Parsed from unstructured LLM response.",
            }
        ]

    @staticmethod
    def _parse_string_array(content: str) -> list[str]:
        """Extract a JSON string array from LLM output."""
        text = content.strip()
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except json.JSONDecodeError:
                pass
        return []

    @staticmethod
    def _derive_deliverable(description: str) -> str:
        """Create a non-empty deliverable label from a macro-step description."""
        desc = re.sub(r"\s+", " ", description).strip()
        if not desc:
            return "Named deliverable"
        desc = re.sub(r"^(derive|prove|show|establish|handle)\s+", "", desc, flags=re.IGNORECASE)
        return desc[:80] or "Named deliverable"

    @classmethod
    def _normalize_macro_steps(cls, macro_steps: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        for index, raw in enumerate(macro_steps, start=1):
            description = str(
                raw.get("description")
                or raw.get("name")
                or f"Macro-step {index}"
            ).strip()
            deliverable = str(raw.get("deliverable") or "").strip()
            if not deliverable:
                deliverable = cls._derive_deliverable(description)
            sub_steps_raw = cls._steps_to_list(
                raw.get("steps", raw.get("sub_steps", []))
            )
            sub_steps: list[str] = []
            sub_step_obligations: list[list[str]] = []
            for step in sub_steps_raw:
                desc = cls._extract_step_description(step)
                if not desc:
                    continue
                sub_steps.append(desc)
                sub_step_obligations.append(cls._extract_step_obligations(step))
            normalized.append(
                {
                    "description": description,
                    "deliverable": deliverable,
                    "steps": sub_steps,
                    "step_obligations": sub_step_obligations,
                }
            )
        return normalized

    @staticmethod
    def _extract_step_description(step) -> str:
        """Extract a meaningful description string from a step.

        The model may return steps as:
        - plain strings: "Prove that n+1 is prime"
        - dicts: {"description": "...", "step": 1} or {"1": "..."}
        - ints: 1
        """
        if isinstance(step, str):
            s = step.strip()
            return s
        if isinstance(step, dict):
            # Try common description keys
            for key in ("description", "desc", "content", "text", "claim", "statement"):
                if key in step and isinstance(step[key], str) and step[key].strip():
                    return step[key].strip()
            # Try: {"1": "description"} pattern (numbered keys)
            for key, val in step.items():
                if isinstance(val, str) and len(val) > 10:
                    return val.strip()
            # Last resort: stringify the whole dict value
            vals = [v for v in step.values() if isinstance(v, str) and len(v) > 5]
            if vals:
                return vals[0].strip()
            return str(step)
        return str(step).strip()

    @staticmethod
    def _normalize_obligation_tag(raw: object) -> str:
        text = str(raw or "").strip().lower()
        aliases = {
            "necessary": "necessary_direction",
            "necessary_direction": "necessary_direction",
            "sufficiency": "sufficiency_direction",
            "sufficient": "sufficiency_direction",
            "sufficiency_direction": "sufficiency_direction",
            "converse": "sufficiency_direction",
            "existence": "existence_or_construction",
            "construction": "existence_or_construction",
            "existence_or_construction": "existence_or_construction",
            "boundary": "boundary_or_small_cases",
            "small_cases": "boundary_or_small_cases",
            "boundary_or_small_cases": "boundary_or_small_cases",
            "final": "final_target_link",
            "final_synthesis": "final_target_link",
            "final_target_link": "final_target_link",
        }
        return aliases.get(text, text)

    @classmethod
    def _extract_step_obligations(cls, step) -> list[str]:
        if not isinstance(step, dict):
            return []
        raw = step.get("obligations", [])
        if not isinstance(raw, list):
            return []
        obligations: list[str] = []
        for item in raw:
            key = cls._normalize_obligation_tag(item)
            if key and key not in obligations:
                obligations.append(key)
        return obligations

    @staticmethod
    def _steps_to_list(raw_steps) -> list:
        """Convert steps from any format to a list of items.

        The model may return steps as:
        - list[str]: ["Prove X", "Show Y"]           (ideal)
        - list[dict]: [{"description": "..."}, ...]   (common)
        - dict: {"1": "Prove X", "2": "Show Y"}      (DeepSeek pattern)
        - dict: {1: "Prove X", 2: "Show Y"}          (numeric keys)
        """
        if isinstance(raw_steps, list):
            return raw_steps
        if isinstance(raw_steps, dict):
            # Convert dict to list of values, sorted by key
            try:
                sorted_keys = sorted(raw_steps.keys(), key=lambda k: int(k))
            except (ValueError, TypeError):
                sorted_keys = sorted(raw_steps.keys(), key=str)
            return [raw_steps[k] for k in sorted_keys]
        return []

    @classmethod
    def _normalize_roadmaps(cls, roadmaps: list[dict]) -> list[dict]:
        """Normalize roadmap shape so flat and hierarchical callers can share it."""
        normalized: list[dict] = []
        for roadmap in roadmaps:
            approach = str(roadmap.get("approach", "")).strip() or "Generated roadmap"
            reasoning = str(roadmap.get("reasoning", "")).strip()
            macro_steps_raw = roadmap.get("macro_steps", [])
            macro_steps = []
            if isinstance(macro_steps_raw, list) and macro_steps_raw:
                macro_steps = cls._normalize_macro_steps(macro_steps_raw)
            raw_steps = cls._steps_to_list(roadmap.get("steps", []))
            steps: list[str] = []
            step_obligations: list[list[str]] = []
            for step in raw_steps:
                desc = cls._extract_step_description(step)
                if not desc:
                    continue
                steps.append(desc)
                step_obligations.append(cls._extract_step_obligations(step))
            if macro_steps:
                flat_steps = []
                flat_obligations: list[list[str]] = []
                for macro in macro_steps:
                    flat_steps.extend(macro["steps"])
                    flat_obligations.extend(
                        macro.get("step_obligations", [[] for _ in macro["steps"]])
                    )
                if flat_steps:
                    steps = flat_steps
                    step_obligations = flat_obligations
            normalized.append(
                {
                    "approach": approach,
                    "steps": steps,
                    "step_obligations": step_obligations,
                    "macro_steps": macro_steps,
                    "reasoning": reasoning,
                }
            )
        return normalized

    @staticmethod
    def _is_overloaded_step(step_description: str) -> bool:
        """Heuristic filter for steps that hide work behind vague language.

        We deliberately do NOT trigger on length, semicolons, or " and ":
        with strong prover models, a long step that names a single concrete
        argument is fine, and shredding it below the natural argument scope
        wastes calls. Only fires on phrases that genuinely paper over the
        reasoning the prover is supposed to carry out.
        """
        lowered = step_description.lower()
        phrases = (
            "combine results",
            "all remaining",
            "standard argument",
            "routine verification",
            "put it all together",
            "finish by",
        )
        return any(phrase in lowered for phrase in phrases)

    async def _refine_overloaded_steps(
        self,
        problem_question: str,
        roadmap: dict,
    ) -> dict:
        """Split overloaded steps after roadmap generation."""
        updated = dict(roadmap)
        if updated.get("macro_steps"):
            refined_macros = []
            flat_steps: list[str] = []
            flat_obligations: list[list[str]] = []
            for macro in updated["macro_steps"]:
                refined_steps: list[str] = []
                refined_obligations: list[list[str]] = []
                macro_obligations = macro.get("step_obligations", [])
                for idx, step in enumerate(macro["steps"]):
                    obligations = macro_obligations[idx] if idx < len(macro_obligations) else []
                    if self._is_overloaded_step(step):
                        split_steps = await self.split_overloaded_step(problem_question, step)
                        refined_steps.extend(split_steps)
                        refined_obligations.extend([list(obligations)] * len(split_steps))
                    else:
                        refined_steps.append(step)
                        refined_obligations.append(list(obligations))
                new_macro = dict(macro)
                new_macro["steps"] = refined_steps
                new_macro["step_obligations"] = refined_obligations
                refined_macros.append(new_macro)
                flat_steps.extend(refined_steps)
                flat_obligations.extend(refined_obligations)
            updated["macro_steps"] = refined_macros
            updated["steps"] = flat_steps
            updated["step_obligations"] = flat_obligations
            return updated

        refined_steps = []
        refined_obligations: list[list[str]] = []
        current_obligations = updated.get("step_obligations", [])
        for idx, step in enumerate(updated.get("steps", [])):
            obligations = current_obligations[idx] if idx < len(current_obligations) else []
            if self._is_overloaded_step(step):
                split_steps = await self.split_overloaded_step(problem_question, step)
                refined_steps.extend(split_steps)
                refined_obligations.extend([list(obligations)] * len(split_steps))
            else:
                refined_steps.append(step)
                refined_obligations.append(list(obligations))
        updated["steps"] = refined_steps
        updated["step_obligations"] = refined_obligations
        return updated

    @classmethod
    def _try_parse_updated_steps(
        cls,
        content: str,
        reference_steps: list[dict] | None = None,
    ) -> list[dict] | None:
        """Attempt to extract updated steps JSON from re-evaluation output.

        The LLM is asked for ``[{"index": int, "description": str}, ...]``
        but frequently returns a bare-string array of new descriptions — the
        schema drift we already tolerate elsewhere in this file. This parser
        must therefore always return ``list[dict]`` (or ``None``), never a
        raw ``list[str]``, because phase1.py iterates with ``updated.get(...)``
        on each element. A type slip used to crash the entire Phase1 run with
        ``AttributeError: 'str' object has no attribute 'get'``.

        *reference_steps* is the remaining-steps payload we sent to the LLM
        (each item ``{"index": int, "description": str}``). When we receive a
        bare-string array we align it positionally with *reference_steps* to
        recover the step indices the LLM implicitly addressed.
        """
        start = content.find("[")
        end = content.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return None

        try:
            raw = json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            return None
        if not isinstance(raw, list) or not raw:
            return None

        ref_indices: list[int] = []
        if reference_steps:
            for ref in reference_steps:
                if isinstance(ref, dict):
                    try:
                        ref_indices.append(int(ref.get("index")))
                    except (TypeError, ValueError):
                        ref_indices.append(0)
        next_index = max(ref_indices or [0]) + 1

        normalized: list[dict] = []
        for position, item in enumerate(raw):
            if isinstance(item, dict):
                idx_raw = item.get("index") or item.get("step_index") or item.get("step")
                desc = item.get("description") or item.get("desc") or item.get("text") or ""
                if not isinstance(desc, str):
                    desc = str(desc)
                desc = desc.strip()
                try:
                    idx = int(idx_raw) if idx_raw is not None else 0
                except (TypeError, ValueError):
                    idx = 0
                if idx <= 0 and position < len(ref_indices):
                    idx = ref_indices[position]
                elif idx <= 0:
                    idx = next_index
                    next_index += 1
                else:
                    next_index = max(next_index, idx + 1)
                if idx and desc:
                    payload = {"index": idx, "description": desc}
                    obligations = cls._extract_step_obligations(item)
                    if obligations:
                        payload["obligations"] = obligations
                    normalized.append(payload)
                continue

            if isinstance(item, str):
                desc = item.strip()
                if not desc:
                    continue
                if position < len(ref_indices) and ref_indices[position]:
                    idx = ref_indices[position]
                else:
                    idx = next_index
                    next_index += 1
                normalized.append({"index": idx, "description": desc})
                continue
            # silently skip nulls / numbers / nested lists — the caller
            # treats an empty updated_steps as "no rewrite" and keeps going.

        return normalized or None
