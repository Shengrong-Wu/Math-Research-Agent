"""The Review Agent -- independent correctness check."""

from __future__ import annotations

import copy

from math_agent.runtime import AgentRuntimeSession

from .base import BaseAgent, ReviewResult

_SYSTEM_PROMPT = (
    "You are a Review Agent in a mathematical proof system. "
    "You are intentionally blind to the proof-development transcript. "
    "As an independent reviewer, your job is to rigorously "
    "evaluate the proof for correctness. Look for logical gaps, "
    "unjustified claims, errors in reasoning, and missing cases. "
    "Be thorough and skeptical."
)


class ReviewAgent(BaseAgent):
    """Independent correctness checker for completed proofs."""

    async def review_proof(
        self,
        problem_question: str,
        complete_proof: str,
        roadmap_summary: str,
        extra_metadata: dict | None = None,
    ) -> ReviewResult:
        review_content = (
            "Evaluate this complete proof for correctness from scratch.\n\n"
            f"Problem:\n{problem_question}\n\n"
            f"Roadmap and trust summary:\n{roadmap_summary}\n\n"
            f"Complete proof:\n{complete_proof}\n\n"
            "Evaluate the proof carefully. For each issue found, describe it "
            "clearly. Then give your overall assessment.\n\n"
            "Respond in this format:\n"
            "VERDICT: PASS | REJECT | UNKNOWN\n"
            "GAPS: (list each gap or issue on its own line, or NONE if no gaps)\n"
            "CONFIDENCE: (a number from 0.0 to 1.0 indicating your confidence "
            "that the proof is correct)\n"
            "REASONING: (your overall assessment)"
        )
        extra = dict(extra_metadata or {})
        doc_counts = {
            "problem_question": len(problem_question),
            "complete_proof": len(complete_proof),
            "roadmap_summary": len(roadmap_summary),
        }
        doc_counts.update(extra.pop("document_char_counts", {}))
        response = await self._request_text(
            review_content,
            system_prompt=_SYSTEM_PROMPT,
            include_context=False,
            record_history=False,
            use_native_session=False,
            metadata={
                "callsite": "review.review_proof",
                "document_char_counts": doc_counts,
                **extra,
            },
        )
        return self._parse_review(response.content)

    @classmethod
    def from_context(
        cls,
        runtime: AgentRuntimeSession,
        context_messages: list,
    ) -> ReviewAgent:
        agent = cls(runtime)
        agent._context = copy.deepcopy(context_messages)
        agent.export_context("thinking-context")
        return agent

    def fork(self) -> ReviewAgent:
        new_agent = ReviewAgent(
            self.runtime.fork(
                role=self.runtime.role,
                root_dir=self.runtime.root_dir,
                workspace=self.runtime.workspace,
            )
        )
        new_agent._context = copy.deepcopy(self._context)
        return new_agent

    @staticmethod
    def _parse_review(content: str) -> ReviewResult:
        gaps: list[str] = []
        confidence = 0.0
        reasoning = ""
        verdict = "UNKNOWN"
        saw_verdict = False
        saw_gaps = False
        saw_confidence = False
        saw_reasoning = False

        section = ""
        for line in content.splitlines():
            stripped = line.strip()
            upper = stripped.upper()

            if upper.startswith("VERDICT:"):
                section = "verdict"
                saw_verdict = True
                remainder = stripped[8:].strip().upper()
                if "PASS" in remainder:
                    verdict = "PASS"
                elif "REJECT" in remainder or "FAIL" in remainder:
                    verdict = "REJECT"
                else:
                    verdict = "UNKNOWN"
            elif upper.startswith("GAPS:"):
                section = "gaps"
                saw_gaps = True
                remainder = stripped[5:].strip()
                if remainder and remainder.upper() != "NONE":
                    gaps.append(remainder)
            elif upper.startswith("CONFIDENCE:"):
                section = "confidence"
                saw_confidence = True
                remainder = stripped[11:].strip()
                try:
                    confidence = float(remainder)
                except ValueError:
                    for token in remainder.split():
                        try:
                            confidence = float(token)
                            break
                        except ValueError:
                            continue
            elif upper.startswith("REASONING:"):
                section = "reasoning"
                saw_reasoning = True
                remainder = stripped[10:].strip()
                if remainder:
                    reasoning = remainder
            elif section == "gaps" and stripped and stripped != "-":
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
            verdict=verdict,
            format_valid=saw_verdict and saw_gaps and saw_confidence and saw_reasoning,
        )
