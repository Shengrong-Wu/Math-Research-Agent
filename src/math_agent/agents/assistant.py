"""The Assistant Agent -- organizes MEMO and NOTES.

Responsible for summarizing proof step results into concise MEMO updates
and detailed NOTES entries, extracting reusable propositions, and compiling
a clean complete proof from accumulated notes.
"""

from __future__ import annotations

from math_agent.llm.base import BaseLLMClient, LLMMessage

from .base import BaseAgent, StepResult

_SYSTEM_PROMPT = (
    "You are an Assistant Agent in a mathematical proof system. "
    "Your role is to organize and summarize proof work. "
    "You maintain a MEMO (concise status updates) and NOTES "
    "(detailed proof records). Be precise and concise."
)


class AssistantAgent(BaseAgent):
    """Organizes MEMO and NOTES for the proof pipeline.

    Summarizes step results, extracts reusable propositions, and compiles
    a complete proof from accumulated notes.
    """

    async def summarize_step_for_memo(
        self,
        step_index: int,
        step_result: StepResult,
    ) -> tuple[str, str]:
        """Produce a brief MEMO update and a detailed NOTES entry for a step.

        For straightforward results the formatting is done locally without
        an LLM call.  If the reasoning text is very long (>2000 chars),
        the LLM is used to compress it into a concise summary.

        Args:
            step_index: Zero-based index of the step.
            step_result: The StepResult from the thinking agent.

        Returns:
            A tuple of (brief_memo_update, detailed_notes_entry).
        """
        verified_tag = "verified" if step_result.verification_passed else "unverified"

        # MEMO: one-line status
        memo_line = (
            f"Step {step_index + 1}: {step_result.status} ({verified_tag})"
        )
        if step_result.error_reason:
            memo_line += f" -- {step_result.error_reason[:120]}"

        # NOTES: full proof detail
        notes_entry = (
            f"=== Step {step_index + 1} [{step_result.status}] ===\n"
            f"Verification: {verified_tag}\n\n"
        )

        if len(step_result.reasoning) > 2000:
            # Use LLM to compress the long reasoning
            compress_content = (
                "Compress the following proof reasoning into a concise but "
                "complete summary preserving all key logical steps:\n\n"
                f"{step_result.reasoning}"
            )
            messages = [LLMMessage(role="user", content=compress_content)]
            response = await self.client.generate(messages, system=_SYSTEM_PROMPT)
            notes_entry += f"Reasoning (compressed):\n{response.content}\n\n"
        else:
            notes_entry += f"Reasoning:\n{step_result.reasoning}\n\n"

        notes_entry += f"Proof detail:\n{step_result.proof_detail}\n"

        if step_result.error_reason:
            notes_entry += f"\nError reason:\n{step_result.error_reason}\n"

        return memo_line, notes_entry

    async def extract_proved_proposition(
        self,
        step_result: StepResult,
    ) -> tuple[str, str] | None:
        """Extract a reusable proposition from a proved step, if any.

        Uses the LLM to determine whether the step established a reusable
        fact and, if so, to produce a concise identifier and statement.

        Args:
            step_result: The StepResult to inspect.

        Returns:
            A (prop_id, statement) tuple, or None if nothing reusable was proved.
        """
        if step_result.status != "PROVED":
            return None

        extract_content = (
            "The following proof step was proved:\n\n"
            f"{step_result.proof_detail}\n\n"
            "If this step establishes a reusable proposition (lemma, claim, "
            "or intermediate result) that later steps could cite, respond "
            "with exactly two lines:\n"
            "ID: <short_identifier>\n"
            "STATEMENT: <precise mathematical statement>\n\n"
            "If nothing reusable was proved, respond with: NONE"
        )

        messages = [
            *self._context,
            LLMMessage(role="user", content=extract_content),
        ]
        response = await self.client.generate(messages, system=_SYSTEM_PROMPT)

        text = response.content.strip()
        if text.upper().startswith("NONE"):
            return None

        prop_id = ""
        statement = ""
        for line in text.splitlines():
            line_stripped = line.strip()
            if line_stripped.upper().startswith("ID:"):
                prop_id = line_stripped[3:].strip()
            elif line_stripped.upper().startswith("STATEMENT:"):
                statement = line_stripped[10:].strip()

        if prop_id and statement:
            return prop_id, statement
        return None

    async def compile_complete_proof(
        self,
        notes_content: str,
        problem_question: str,
    ) -> str:
        """Compile a clean, complete proof from the full NOTES.

        Produces a polished proof suitable for the formal verification
        phase (Phase 2).

        Args:
            notes_content: The accumulated NOTES containing all step proofs.
            problem_question: The original problem statement.

        Returns:
            A clean, complete proof as a single string.
        """
        compile_content = (
            f"Problem:\n{problem_question}\n\n"
            f"Proof notes from all steps:\n{notes_content}\n\n"
            "Compile a clean, complete, and self-contained proof from these "
            "notes. The proof should:\n"
            "  1. State the theorem clearly\n"
            "  2. Present all steps in logical order\n"
            "  3. Ensure no gaps between steps\n"
            "  4. Use precise mathematical language\n"
            "  5. Be suitable for formalization in Lean 4\n\n"
            "Write only the proof, no commentary."
        )

        messages = [
            *self._context,
            LLMMessage(role="user", content=compile_content),
        ]
        response = await self.client.generate(messages, system=_SYSTEM_PROMPT)

        self.add_to_context(LLMMessage(role="user", content=compile_content))
        self.add_to_context(LLMMessage(role="assistant", content=response.content))

        return response.content
