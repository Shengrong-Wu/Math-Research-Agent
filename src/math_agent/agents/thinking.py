"""The Thinking Agent -- main proof reasoning worker.

Responsible for generating proof roadmaps, working through individual proof
steps, self-verifying results, and re-evaluating the roadmap as work progresses.
"""

from __future__ import annotations

import copy
import json

from math_agent.llm.base import BaseLLMClient, LLMMessage

from .base import BaseAgent, RoadmapEvaluation, StepResult

_SYSTEM_PROMPT = (
    "You are a Thinking Agent in a mathematical proof system. "
    "Your role is to reason carefully about mathematical proofs, "
    "generate proof strategies, work through individual proof steps "
    "with rigour, and verify your own work. "
    "Always show your reasoning clearly. "
    "When you prove a step, write out the full logical argument."
)


class ThinkingAgent(BaseAgent):
    """Main proof reasoning worker.

    Generates proof roadmaps, works through proof steps one at a time,
    self-verifies each step, and re-evaluates the overall roadmap after
    each completed step.
    """

    async def generate_roadmaps(
        self,
        problem_question: str,
        memo_content: str | None = None,
        count: int = 3,
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

        Returns:
            A list of roadmap dicts.
        """
        if memo_content is not None:
            count = 1

        user_content = f"Problem:\n{problem_question}\n\n"
        if memo_content:
            user_content += (
                f"MEMO from a previous attempt (use this to improve your strategy):\n"
                f"{memo_content}\n\n"
            )
        user_content += (
            f"Generate exactly {count} distinct proof roadmap(s). "
            "For each roadmap, provide:\n"
            '  - "approach": a concise description of the proof strategy\n'
            '  - "steps": an ordered list of step descriptions (strings)\n'
            '  - "reasoning": why this approach is promising\n\n'
            "Respond with a JSON array of roadmap objects and nothing else."
        )

        messages = [
            *self._context,
            LLMMessage(role="user", content=user_content),
        ]

        response = await self.client.generate(messages, system=_SYSTEM_PROMPT)

        self.add_to_context(LLMMessage(role="user", content=user_content))
        self.add_to_context(LLMMessage(role="assistant", content=response.content))

        return self._parse_roadmaps(response.content)

    async def work_step(
        self,
        problem_question: str,
        roadmap_summary: str,
        step_description: str,
        step_index: int,
        context_notes: str = "",
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
        prove_content = (
            f"Problem: {problem_question}\n\n"
            f"Overall proof roadmap:\n{roadmap_summary}\n\n"
        )
        if context_notes:
            prove_content += f"Context from previous steps:\n{context_notes}\n\n"
        prove_content += (
            f"Step {step_index + 1}: {step_description}\n\n"
            "Prove this step. Show all reasoning and write a complete, "
            "rigorous proof for this step."
        )

        prove_messages = [
            *self._context,
            LLMMessage(role="user", content=prove_content),
        ]
        prove_response = await self.client.generate(prove_messages, system=_SYSTEM_PROMPT)

        self.add_to_context(LLMMessage(role="user", content=prove_content))
        self.add_to_context(LLMMessage(role="assistant", content=prove_response.content))

        # --- Phase 2: self-verify ---
        verify_content = (
            "Check whether your proof for this step is correct. "
            "If correct, respond with VERIFIED and a brief confirmation. "
            "If not correct, respond with INVALID and explain why."
        )

        verify_messages = [
            *self._context,
            LLMMessage(role="user", content=verify_content),
        ]
        verify_response = await self.client.generate(verify_messages, system=_SYSTEM_PROMPT)

        self.add_to_context(LLMMessage(role="user", content=verify_content))
        self.add_to_context(LLMMessage(role="assistant", content=verify_response.content))

        verification_passed = "VERIFIED" in verify_response.content.upper()
        status = "PROVED" if verification_passed else "FAILED"
        error_reason = "" if verification_passed else verify_response.content

        return StepResult(
            step_index=step_index,
            status=status,
            reasoning=prove_response.content,
            proof_detail=prove_response.content,
            verification_passed=verification_passed,
            error_reason=error_reason,
        )

    async def re_evaluate_roadmap(
        self,
        problem_question: str,
        roadmap_summary: str,
        completed_steps: list[dict],
        remaining_steps: list[dict],
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
        eval_content = (
            f"Problem: {problem_question}\n\n"
            f"Overall roadmap:\n{roadmap_summary}\n\n"
            f"Completed steps:\n{json.dumps(completed_steps, indent=2)}\n\n"
            f"Remaining steps:\n{json.dumps(remaining_steps, indent=2)}\n\n"
            "Given that the completed steps are proved, do the remaining "
            "steps still make sense? Are they still plausible given what "
            "was proved?\n\n"
            "If the roadmap is still on track, respond with ON_TRACK and "
            "a brief explanation.\n"
            "If not, respond with NEEDS_UPDATE, explain why, and provide "
            "the updated remaining steps as a JSON array of step description "
            "objects."
        )

        messages = [
            *self._context,
            LLMMessage(role="user", content=eval_content),
        ]
        response = await self.client.generate(messages, system=_SYSTEM_PROMPT)

        self.add_to_context(LLMMessage(role="user", content=eval_content))
        self.add_to_context(LLMMessage(role="assistant", content=response.content))

        on_track = "ON_TRACK" in response.content.upper()
        updated_steps = None
        if not on_track:
            updated_steps = self._try_parse_updated_steps(response.content)

        return RoadmapEvaluation(
            on_track=on_track,
            updated_steps=updated_steps,
            reasoning=response.content,
        )

    def fork(self) -> ThinkingAgent:
        """Create a copy with the same client and a deep copy of the context."""
        new_agent = ThinkingAgent(self.client)
        new_agent._context = copy.deepcopy(self._context)
        return new_agent

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_roadmaps(content: str) -> list[dict]:
        """Best-effort parse of JSON roadmaps from LLM output."""
        content = content.strip()

        # Try to find a JSON array in the response
        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end != -1:
            try:
                return json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                pass

        # Fallback: wrap the whole response as a single roadmap
        return [
            {
                "approach": "LLM-generated roadmap (raw)",
                "steps": [content],
                "reasoning": "Could not parse structured roadmaps from response.",
            }
        ]

    @staticmethod
    def _try_parse_updated_steps(content: str) -> list[dict] | None:
        """Attempt to extract updated steps JSON from re-evaluation output."""
        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end != -1:
            try:
                return json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                pass
        return None
