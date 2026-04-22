"""The Assistant Agent -- organizes MEMO and NOTES."""

from __future__ import annotations

from .base import BaseAgent, StepResult

_SYSTEM_PROMPT = (
    "You are an Assistant Agent in a mathematical proof system. "
    "Your role is to organize and summarize proof work. "
    "You maintain a MEMO (concise status updates) and NOTES "
    "(detailed proof records). Be precise and concise."
)


class AssistantAgent(BaseAgent):
    """Organizes MEMO and NOTES for the proof pipeline."""

    async def summarize_step_for_memo(
        self,
        step_index: int,
        step_result: StepResult,
    ) -> tuple[str, str]:
        verified_tag = (
            step_result.verification_outcome.lower()
            if step_result.verification_outcome
            else ("verified" if step_result.verification_passed else "unverified")
        )

        memo_line = f"Step {step_index}: {step_result.status} ({verified_tag})"
        if step_result.error_reason:
            memo_line += f" -- {step_result.error_reason[:120]}"

        notes_entry = (
            f"=== Step {step_index} [{step_result.status}] ===\n"
            f"Verification: {verified_tag}\n\n"
        )
        if step_result.verification_notes:
            notes_entry += f"Verification notes:\n{step_result.verification_notes}\n\n"
        if step_result.derived_claim:
            notes_entry += f"Derived claim:\n{step_result.derived_claim}\n\n"
        if step_result.false_claim:
            notes_entry += f"False claim:\n{step_result.false_claim}\n\n"

        if len(step_result.reasoning) > 2000:
            compress_content = (
                "Compress the following proof reasoning into a concise but "
                "complete summary preserving all key logical steps:\n\n"
                f"{step_result.reasoning}"
            )
            response = await self._request_text(
                compress_content,
                system_prompt=_SYSTEM_PROMPT,
                include_context=False,
                record_history=False,
                metadata={
                    "callsite": "assistant.summarize_step_for_memo",
                    "document_char_counts": {"reasoning": len(step_result.reasoning)},
                },
            )
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
        response = await self._request_text(
            extract_content,
            system_prompt=_SYSTEM_PROMPT,
            metadata={
                "callsite": "assistant.extract_proved_proposition",
                "document_char_counts": {"proof_detail": len(step_result.proof_detail)},
            },
        )

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
        extra_metadata: dict | None = None,
    ) -> str:
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
        extra = dict(extra_metadata or {})
        doc_counts = {
            "notes_content": len(notes_content),
            "problem_question": len(problem_question),
        }
        doc_counts.update(extra.pop("document_char_counts", {}))
        response = await self._request_text(
            compile_content,
            system_prompt=_SYSTEM_PROMPT,
            include_context=False,
            record_history=False,
            use_native_session=False,
            metadata={
                "callsite": "assistant.compile_complete_proof",
                "document_char_counts": doc_counts,
                **extra,
            },
        )
        return response.content
