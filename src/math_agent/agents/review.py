"""The Review Agent -- independent correctness check.

Created by forking the Thinking Agent so it has full context of the proof
development, then acts as an independent reviewer to find gaps, logical
errors, or unjustified steps.
"""

from __future__ import annotations

import copy

from math_agent.llm.base import BaseLLMClient, LLMMessage

from .base import BaseAgent, ReviewResult
from .thinking import ThinkingAgent

_SYSTEM_PROMPT = (
    "You are a Review Agent in a mathematical proof system. "
    "You have observed the entire proof development process. "
    "Now, as an independent reviewer, your job is to rigorously "
    "evaluate the proof for correctness. Look for logical gaps, "
    "unjustified claims, errors in reasoning, and missing cases. "
    "Be thorough and skeptical."
)


class ReviewAgent(BaseAgent):
    """Independent correctness checker for completed proofs.

    Created from a forked ThinkingAgent so it shares the full context
    of the proof development, then evaluates the proof independently.
    """

    async def review_proof(
        self,
        problem_question: str,
        complete_proof: str,
        roadmap_summary: str,
    ) -> ReviewResult:
        """Independently evaluate a complete proof.

        Looks for gaps, logical errors, unjustified steps, and missing
        cases. Returns a structured ReviewResult.

        Args:
            problem_question: The original problem statement.
            complete_proof: The compiled complete proof to review.
            roadmap_summary: Summary of the proof roadmap used.

        Returns:
            A ReviewResult with gap analysis and confidence score.
        """
        review_content = (
            "You have seen the proof development. Now, as an independent "
            "reviewer, evaluate this complete proof for correctness.\n\n"
            f"Problem:\n{problem_question}\n\n"
            f"Proof roadmap:\n{roadmap_summary}\n\n"
            f"Complete proof:\n{complete_proof}\n\n"
            "Evaluate the proof carefully. For each issue found, describe it "
            "clearly. Then give your overall assessment.\n\n"
            "Respond in this format:\n"
            "GAPS: (list each gap or issue on its own line, or NONE if no gaps)\n"
            "CONFIDENCE: (a number from 0.0 to 1.0 indicating your confidence "
            "that the proof is correct)\n"
            "REASONING: (your overall assessment)"
        )

        messages = [
            *self._context,
            LLMMessage(role="user", content=review_content),
        ]
        response = await self.client.generate(messages, system=_SYSTEM_PROMPT)

        self.add_to_context(LLMMessage(role="user", content=review_content))
        self.add_to_context(LLMMessage(role="assistant", content=response.content))

        return self._parse_review(response.content)

    @classmethod
    def from_thinking_agent(cls, thinking: ThinkingAgent) -> ReviewAgent:
        """Create a ReviewAgent by forking a ThinkingAgent.

        The new agent shares the same LLM client and receives a deep
        copy of the thinking agent's conversation context.

        Args:
            thinking: The ThinkingAgent to fork from.

        Returns:
            A new ReviewAgent with copied context.
        """
        agent = cls(thinking.client)
        agent._context = copy.deepcopy(thinking._context)
        return agent

    def fork(self) -> ReviewAgent:
        """Create a copy with the same client and a deep copy of the context."""
        new_agent = ReviewAgent(self.client)
        new_agent._context = copy.deepcopy(self._context)
        return new_agent

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_review(content: str) -> ReviewResult:
        """Parse the LLM review response into a ReviewResult."""
        gaps: list[str] = []
        confidence = 0.0
        reasoning = ""

        section = ""
        for line in content.splitlines():
            stripped = line.strip()
            upper = stripped.upper()

            if upper.startswith("GAPS:"):
                section = "gaps"
                remainder = stripped[5:].strip()
                if remainder and remainder.upper() != "NONE":
                    gaps.append(remainder)
            elif upper.startswith("CONFIDENCE:"):
                section = "confidence"
                remainder = stripped[11:].strip()
                try:
                    confidence = float(remainder)
                except ValueError:
                    # Try to extract a number from the remainder
                    for token in remainder.split():
                        try:
                            confidence = float(token)
                            break
                        except ValueError:
                            continue
            elif upper.startswith("REASONING:"):
                section = "reasoning"
                remainder = stripped[10:].strip()
                if remainder:
                    reasoning = remainder
            elif section == "gaps" and stripped and stripped != "-":
                # Strip leading dashes/bullets
                gap_text = stripped.lstrip("-").lstrip("*").lstrip().lstrip(".")
                if gap_text and gap_text.upper() != "NONE":
                    gaps.append(gap_text.strip())
            elif section == "reasoning":
                reasoning += "\n" + stripped if reasoning else stripped

        confidence = max(0.0, min(1.0, confidence))

        return ReviewResult(
            has_gaps=len(gaps) > 0,
            gaps=gaps,
            confidence=confidence,
            reasoning=reasoning.strip(),
        )
