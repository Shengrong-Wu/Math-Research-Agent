"""The CLI Agent -- writes Lean 4 code.

Responsible for generating Lean 4 skeleton code from a complete proof,
fixing compiler errors, eliminating sorry placeholders with actual proofs,
and converting sorry placeholders into axioms (external claims) when needed.
"""

from __future__ import annotations

import json

from math_agent.llm.base import BaseLLMClient, LLMMessage

from .base import BaseAgent

_SYSTEM_PROMPT = (
    "You are a CLI Agent in a mathematical proof system. "
    "Your role is to write correct Lean 4 code that formalizes "
    "mathematical proofs. Write clean, idiomatic Lean 4. "
    "Use Mathlib conventions where appropriate. "
    "Always aim for code that compiles without errors."
)


class CLIAgent(BaseAgent):
    """Writes and maintains Lean 4 code for formal verification.

    Generates skeleton code from a complete proof, fixes compiler errors,
    replaces sorry placeholders with actual proofs, and converts sorry
    placeholders into axioms when a formal proof is not feasible.
    """

    async def generate_skeleton(
        self,
        proof: str,
        module_names: list[str],
    ) -> dict[str, str]:
        """Generate Lean 4 skeleton code from a complete proof.

        Produces one Lean 4 module per entry in *module_names*, with sorry
        placeholders where formal proofs are needed.

        Args:
            proof: The complete mathematical proof to formalize.
            module_names: List of Lean module names to generate.

        Returns:
            A dict mapping module_name -> lean_code.
        """
        gen_content = (
            f"Complete proof to formalize:\n{proof}\n\n"
            f"Generate Lean 4 code split across these modules: "
            f"{json.dumps(module_names)}\n\n"
            "For each module, produce compilable Lean 4 code. Use sorry "
            "as a placeholder where formal proofs are needed.\n\n"
            "Respond with a JSON object mapping module name to Lean 4 code "
            "string. Example:\n"
            '{"Module1": "-- Lean 4 code...", "Module2": "-- Lean 4 code..."}\n\n'
            "Respond with only the JSON object."
        )

        messages = [
            *self._context,
            LLMMessage(role="user", content=gen_content),
        ]
        response = await self.client.generate(messages, system=_SYSTEM_PROMPT)

        self.add_to_context(LLMMessage(role="user", content=gen_content))
        self.add_to_context(LLMMessage(role="assistant", content=response.content))

        return self._parse_module_dict(response.content, module_names)

    async def fix_compiler_error(
        self,
        module_name: str,
        lean_code: str,
        error: str,
    ) -> str:
        """Attempt to fix a Lean 4 compiler error.

        Args:
            module_name: Name of the module with the error.
            lean_code: Current Lean 4 code that failed to compile.
            error: The compiler error message.

        Returns:
            The fixed Lean 4 code.
        """
        fix_content = (
            f"Module: {module_name}\n\n"
            f"Current Lean 4 code:\n```lean\n{lean_code}\n```\n\n"
            f"Compiler error:\n{error}\n\n"
            "Fix the code so it compiles. Return only the complete fixed "
            "Lean 4 code, no explanation."
        )

        messages = [
            *self._context,
            LLMMessage(role="user", content=fix_content),
        ]
        response = await self.client.generate(messages, system=_SYSTEM_PROMPT)

        self.add_to_context(LLMMessage(role="user", content=fix_content))
        self.add_to_context(LLMMessage(role="assistant", content=response.content))

        return self._extract_lean_code(response.content)

    async def eliminate_sorry(
        self,
        module_name: str,
        lean_code: str,
        sorry_context: str,
    ) -> str:
        """Attempt to replace a sorry placeholder with an actual proof.

        Args:
            module_name: Name of the module containing the sorry.
            lean_code: Current Lean 4 code with the sorry.
            sorry_context: Context around the sorry (goal state, etc.).

        Returns:
            Updated Lean 4 code with the sorry replaced by a proof.
        """
        elim_content = (
            f"Module: {module_name}\n\n"
            f"Current Lean 4 code:\n```lean\n{lean_code}\n```\n\n"
            f"Sorry context (goal state and surrounding code):\n{sorry_context}\n\n"
            "Replace the sorry with an actual Lean 4 proof. "
            "Return the complete updated Lean 4 code, no explanation."
        )

        messages = [
            *self._context,
            LLMMessage(role="user", content=elim_content),
        ]
        response = await self.client.generate(messages, system=_SYSTEM_PROMPT)

        self.add_to_context(LLMMessage(role="user", content=elim_content))
        self.add_to_context(LLMMessage(role="assistant", content=response.content))

        return self._extract_lean_code(response.content)

    async def accept_external_claim(
        self,
        module_name: str,
        lean_code: str,
        sorry_context: str,
    ) -> str:
        """Convert a sorry placeholder into an axiom (external claim).

        Used when a sorry cannot be eliminated and the claim must be
        accepted without formal proof.

        Args:
            module_name: Name of the module containing the sorry.
            lean_code: Current Lean 4 code with the sorry.
            sorry_context: Context around the sorry (goal state, etc.).

        Returns:
            Updated Lean 4 code with the sorry converted to an axiom.
        """
        axiom_content = (
            f"Module: {module_name}\n\n"
            f"Current Lean 4 code:\n```lean\n{lean_code}\n```\n\n"
            f"Sorry context (goal state and surrounding code):\n{sorry_context}\n\n"
            "This sorry cannot be formally proved. Convert it into an axiom "
            "(external claim) so that the rest of the code can proceed. "
            "Use the Lean 4 'axiom' keyword and give it a descriptive name. "
            "Return the complete updated Lean 4 code, no explanation."
        )

        messages = [
            *self._context,
            LLMMessage(role="user", content=axiom_content),
        ]
        response = await self.client.generate(messages, system=_SYSTEM_PROMPT)

        self.add_to_context(LLMMessage(role="user", content=axiom_content))
        self.add_to_context(LLMMessage(role="assistant", content=response.content))

        return self._extract_lean_code(response.content)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_module_dict(content: str, module_names: list[str]) -> dict[str, str]:
        """Parse a JSON module dict from the LLM response."""
        content = content.strip()

        # Try to find a JSON object in the response
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            try:
                parsed = json.loads(content[start : end + 1])
                if isinstance(parsed, dict):
                    return {k: str(v) for k, v in parsed.items()}
            except json.JSONDecodeError:
                pass

        # Fallback: put everything in the first module
        if module_names:
            return {module_names[0]: CLIAgent._extract_lean_code(content)}
        return {"Main": CLIAgent._extract_lean_code(content)}

    @staticmethod
    def _extract_lean_code(content: str) -> str:
        """Extract Lean 4 code from an LLM response.

        Handles responses wrapped in markdown code fences.
        """
        content = content.strip()

        # Try to extract from code fences
        if "```lean" in content:
            start = content.find("```lean")
            start = content.find("\n", start) + 1
            end = content.find("```", start)
            if end != -1:
                return content[start:end].strip()

        if "```" in content:
            start = content.find("```")
            start = content.find("\n", start) + 1
            end = content.find("```", start)
            if end != -1:
                return content[start:end].strip()

        return content
