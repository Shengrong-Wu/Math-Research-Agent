"""The Formalizer Agent -- Lean-oriented code generation helper."""

from __future__ import annotations

import copy
import re

from .base import BaseAgent
from .prompt_loader import render_prompt_section

_PROMPT_BUNDLE = "thinking_bundle"
_SYSTEM_PROMPT = """\
You are a Formalizer Agent in a mathematical proof system.
Your role is to translate mathematically plausible statements into Lean 4
theorem and lemma skeletons that are type-correct or close to type-correct.
Prefer precise theorem statements, explicit imports, and conservative use of
`sorry` over invented Mathlib facts or unsafe guesses.
"""


def _extract_lean_code(text: str) -> str:
    code = text.strip()
    if "```lean" in code:
        match = re.search(r"```lean\n(.*?)```", code, re.DOTALL)
        if match:
            return match.group(1).strip()
    if "```" in code:
        match = re.search(r"```\n(.*?)```", code, re.DOTALL)
        if match:
            return match.group(1).strip()
    return code


class FormalizerAgent(BaseAgent):
    """Lean-facing helper for statement and sketch generation."""

    async def formalize_statement(
        self,
        problem_question: str,
        approach: str,
    ) -> str:
        content = render_prompt_section(
            _PROMPT_BUNDLE,
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
                "callsite": "formalizer.formalize_statement",
                "document_char_counts": {
                    "problem_question": len(problem_question),
                    "approach": len(approach),
                },
            },
        )
        return _extract_lean_code(response.content)

    async def formalize_step_sketch(
        self,
        problem_question: str,
        step_description: str,
        proved_propositions: list[str],
    ) -> str:
        props_text = (
            "\n".join(f"- {item}" for item in proved_propositions)
            if proved_propositions
            else "(none)"
        )
        content = render_prompt_section(
            _PROMPT_BUNDLE,
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
                "callsite": "formalizer.formalize_step_sketch",
                "document_char_counts": {
                    "problem_question": len(problem_question),
                    "step_description": len(step_description),
                    "proved_propositions_text": len(props_text),
                },
            },
        )
        return _extract_lean_code(response.content)

    def fork(self) -> FormalizerAgent:
        new_agent = FormalizerAgent(
            self.runtime.fork(
                role=self.runtime.role,
                root_dir=self.runtime.root_dir,
                workspace=self.runtime.workspace,
            )
        )
        new_agent._context = copy.deepcopy(self._context)
        return new_agent
