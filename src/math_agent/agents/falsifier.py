"""The Blind Falsifier Agent -- independent counterexample checker.

Sees ONLY the problem statement and claimed answer/proof, with NO context
from the proof development process. Its sole job is to try to break the
claimed result by:

1. Testing small cases and boundary values
2. Checking bidirectionality (necessary AND sufficient)
3. Running computational verification in a Python sandbox
4. Looking for counterexamples and missing cases
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from math_agent.runtime import RuntimeMessage

from .base import BaseAgent

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a Blind Falsifier -- a mathematical skeptic.

You are given ONLY a problem statement and a claimed answer or proof.
You have NOT seen how the proof was developed. You have NO context about
the reasoning process. You must evaluate the claim from scratch.

Your ONLY job is to find problems with the claimed result:
- Counterexamples that disprove the claim
- Missing cases or directions (e.g., proved necessary but not sufficient)
- Boundary conditions that fail
- Logical gaps in the argument

You are ADVERSARIAL. Assume the proof is wrong until you convince yourself
otherwise. Be especially suspicious of:
- "Find all" problems where only some solutions might be found
- Sufficiency: does each claimed solution ACTUALLY satisfy all conditions?
- Claims about infinite families: can you test specific members?

You have access to a Python sandbox. Generate Python code to:
- Test claimed solutions against the original condition
- Search for counterexamples by brute force
- Verify boundary cases

When generating Python code:
- Use only standard library + sympy (for math)
- Keep code simple and focused on ONE test per block
- Print clear PASS/FAIL results with explanations
- Always test both directions for "if and only if" claims
- Test the ORIGINAL claim under its stated assumptions.
- Do NOT use Python blocks for weakened-hypothesis or dropped-assumption
  negative controls; if those are worth mentioning, discuss them in prose.
"""


@dataclass
class FalsifyResult:
    """Result of a blind falsification attempt."""

    verdict: str  # "PASS" | "FAIL" | "UNCERTAIN"
    has_counterexample: bool = False
    counterexample: str = ""
    missing_cases: list[str] = field(default_factory=list)
    python_checks: list[PythonCheckResult] = field(default_factory=list)
    reasoning: str = ""
    suggestions: list[str] = field(default_factory=list)


@dataclass
class PythonCheckResult:
    """Result of running a Python verification script."""

    description: str
    code: str
    stdout: str
    stderr: str
    passed: bool
    timed_out: bool = False


class FalsifierAgent(BaseAgent):
    """Blind falsifier -- sees only problem + claimed answer.

    This agent receives NO context from the proof development process.
    It starts with an empty conversation context and evaluates the
    claimed result from scratch, with emphasis on finding counterexamples
    and testing sufficiency.
    """

    def __init__(self, runtime):
        super().__init__(runtime)
        # Explicitly empty context -- this agent is BLIND
        self._context = []

    async def falsify(
        self,
        problem_question: str,
        claimed_answer: str,
        *,
        max_python_checks: int = 5,
        python_timeout: float = 30.0,
        extra_metadata: dict | None = None,
    ) -> FalsifyResult:
        """Try to falsify a claimed answer/proof.

        This is the main entry point. The agent:
        1. Analyzes the claim for potential weaknesses
        2. Generates Python code to test the claim
        3. Runs the Python checks in a sandbox
        4. Delivers a verdict

        Args:
            problem_question: The original problem statement.
            claimed_answer: The claimed answer and/or proof summary.
            max_python_checks: Max number of Python scripts to run.
            python_timeout: Timeout per Python script in seconds.

        Returns:
            A FalsifyResult with verdict and any counterexamples found.
        """
        # Step 1: Ask the falsifier to analyze and generate tests
        analysis_prompt = (
            f"PROBLEM STATEMENT:\n{problem_question}\n\n"
            f"CLAIMED ANSWER/PROOF:\n{claimed_answer}\n\n"
            "---\n\n"
            "You are a blind falsifier. You have NOT seen how this proof "
            "was developed. Analyze this claim skeptically.\n\n"
            "First, identify potential weaknesses:\n"
            "1. What COULD be wrong with this claim?\n"
            "2. Are there boundary cases to check?\n"
            "3. Does the proof establish BOTH necessary and sufficient conditions?\n"
            "4. For 'find all' problems: are there solutions the proof might have missed?\n\n"
            "Then, generate Python test code to check the claim. Wrap each test "
            "in a ```python code block. Each test should:\n"
            "- Test ONE specific aspect of the claim\n"
            "- Print clear results (PASS/FAIL with explanation)\n"
            "- Use only standard library + sympy\n"
            "- Be self-contained (no imports between blocks)\n"
            "- Test the original theorem/claim as stated, not a weakened variant\n\n"
            "Generate at least 2-3 different tests covering:\n"
            "- Forward direction: do claimed solutions actually satisfy the condition?\n"
            "- Backward direction: are there counterexamples under the original assumptions?\n"
            "- Boundary/edge cases\n\n"
            "IMPORTANT: For 'find all' problems, ALWAYS brute-force check small "
            "values to find the complete solution set and compare with the claim.\n"
            "IMPORTANT: Do NOT write Python tests that intentionally drop or weaken "
            "the theorem's assumptions. If you want to discuss whether assumptions "
            "are necessary, do that in prose only."
        )

        # Use empty context -- this is the BLIND falsifier
        extra = dict(extra_metadata or {})
        doc_counts = {
            "problem_question": len(problem_question),
            "claimed_answer": len(claimed_answer),
        }
        doc_counts.update(extra.pop("document_char_counts", {}))
        response = await self._request_text(
            analysis_prompt,
            system_prompt=_SYSTEM_PROMPT,
            include_context=False,
            record_history=False,
            use_native_session=False,
            metadata={
                "callsite": "falsifier.analysis",
                "document_char_counts": doc_counts,
                **extra,
            },
        )
        analysis = response.content

        # Step 2: Extract and run Python code blocks
        python_blocks = self._extract_python_blocks(analysis)
        check_results: list[PythonCheckResult] = []

        for i, (description, code) in enumerate(python_blocks[:max_python_checks]):
            logger.info(
                "Falsifier: running Python check %d/%d: %s",
                i + 1, len(python_blocks), description[:60],
            )
            check = await self._run_python_sandbox(
                code, description, timeout=python_timeout,
            )
            check_results.append(check)

        # Step 3: Ask the falsifier for a final verdict
        verdict_prompt = (
            f"Here are the results of your Python tests:\n\n"
        )
        for i, check in enumerate(check_results, 1):
            status = "PASSED" if check.passed else "FAILED"
            if check.timed_out:
                status = "TIMED OUT"
            verdict_prompt += (
                f"Test {i}: {check.description}\n"
                f"Status: {status}\n"
                f"Output:\n{check.stdout[:500]}\n"
            )
            if check.stderr:
                verdict_prompt += f"Errors:\n{check.stderr[:300]}\n"
            verdict_prompt += "\n"

        verdict_prompt += (
            "Based on these test results AND your initial analysis, "
            "give your FINAL VERDICT.\n\n"
            "Respond in this EXACT format:\n"
            "VERDICT: PASS | FAIL | UNCERTAIN\n"
            "COUNTEREXAMPLE: (describe any counterexample found, or NONE)\n"
            "MISSING_CASES: (list any missing cases, one per line, or NONE)\n"
            "REASONING: (your overall assessment)\n"
            "SUGGESTIONS: (what should be fixed or checked further, or NONE)"
        )

        verdict_response = await self.runtime.invoke(
            system_prompt=_SYSTEM_PROMPT,
            transcript=[
                RuntimeMessage(role="user", content=analysis_prompt),
                RuntimeMessage(role="assistant", content=analysis),
            ],
            prompt=verdict_prompt,
            use_native_session=False,
            metadata={
                "callsite": "falsifier.verdict",
                "document_char_counts": {
                    "analysis_prompt": len(analysis_prompt),
                    "analysis": len(analysis),
                    "verdict_prompt": len(verdict_prompt),
                },
                **{
                    key: value
                    for key, value in (extra_metadata or {}).items()
                    if key != "document_char_counts"
                },
            },
        )

        return self._parse_verdict(verdict_response.content, check_results)

    # ------------------------------------------------------------------
    # Python sandbox
    # ------------------------------------------------------------------

    async def _run_python_sandbox(
        self,
        code: str,
        description: str,
        *,
        timeout: float = 30.0,
    ) -> PythonCheckResult:
        """Execute Python code in a subprocess sandbox.

        The code runs in a separate Python process with no access to
        the parent process's memory or environment (except PYTHONPATH
        for sympy).

        Args:
            code: Python code to execute.
            description: Human-readable description of what this checks.
            timeout: Maximum execution time in seconds.

        Returns:
            A PythonCheckResult with stdout, stderr, and pass/fail status.
        """
        # Write code to a temp file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            prefix="falsifier_",
        ) as f:
            f.write(code)
            tmp_path = Path(f.name)

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(tmp_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
                stdout = stdout_bytes.decode(errors="replace")
                stderr = stderr_bytes.decode(errors="replace")
                timed_out = False
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                stdout = ""
                stderr = f"Timed out after {timeout}s"
                timed_out = True

            # Determine pass/fail from output
            passed = self._check_output_passed(stdout, stderr, timed_out)

            return PythonCheckResult(
                description=description,
                code=code,
                stdout=stdout,
                stderr=stderr,
                passed=passed,
                timed_out=timed_out,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @staticmethod
    def _check_output_passed(stdout: str, stderr: str, timed_out: bool) -> bool:
        """Heuristically determine if a Python check passed.

        Only explicit PASS counts as a pass. Silent or ambiguous output is
        treated as inconclusive so the falsifier fails closed.
        """
        if timed_out:
            return False

        combined = (stdout + stderr).upper()

        # Explicit signals
        has_fail = bool(re.search(r"\bFAIL\b", combined))
        has_counterexample = bool(re.search(r"\bCOUNTEREXAMPLE\b", combined))
        has_error = bool(re.search(r"\bError\b", stderr)) and "Traceback" in stderr
        has_pass = bool(re.search(r"\bPASS\b", combined))

        if has_fail or has_counterexample:
            return False
        if has_error:
            return False
        return has_pass

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_python_blocks(content: str) -> list[tuple[str, str]]:
        """Extract Python code blocks from LLM output.

        Returns a list of (description, code) tuples.
        """
        blocks: list[tuple[str, str]] = []

        # Find all ```python ... ``` blocks
        pattern = re.compile(
            r"```python\s*\n(.*?)```",
            re.DOTALL,
        )

        matches = list(pattern.finditer(content))

        for i, match in enumerate(matches):
            code = match.group(1).strip()

            # Try to find a description before the code block
            # Look at the text between previous block end and this block start
            if i == 0:
                preceding = content[:match.start()]
            else:
                preceding = content[matches[i - 1].end():match.start()]

            # Extract last non-empty line as description
            desc_lines = [
                l.strip() for l in preceding.strip().splitlines()
                if l.strip() and not l.strip().startswith("```")
            ]
            description = desc_lines[-1] if desc_lines else f"Python check {i + 1}"
            # Clean up markdown formatting from description
            description = re.sub(r"^[#*\-\d.]+\s*", "", description).strip()
            if len(description) > 100:
                description = description[:97] + "..."

            blocks.append((description, code))

        return blocks

    @staticmethod
    def _parse_verdict(
        content: str,
        python_checks: list[PythonCheckResult],
    ) -> FalsifyResult:
        """Parse the falsifier's verdict response."""
        verdict = "UNCERTAIN"
        counterexample = ""
        missing_cases: list[str] = []
        reasoning = ""
        suggestions: list[str] = []

        section = ""
        for line in content.splitlines():
            stripped = line.strip()
            upper = stripped.upper()

            if upper.startswith("VERDICT:"):
                section = "verdict"
                remainder = stripped[8:].strip().upper()
                if "FAIL" in remainder:
                    verdict = "FAIL"
                elif "PASS" in remainder:
                    verdict = "PASS"
                else:
                    verdict = "UNCERTAIN"
            elif upper.startswith("COUNTEREXAMPLE:"):
                section = "counterexample"
                remainder = stripped[15:].strip()
                if remainder.upper() != "NONE":
                    counterexample = remainder
            elif upper.startswith("MISSING_CASES:") or upper.startswith("MISSING CASES:"):
                section = "missing"
                remainder = stripped[14:].strip()
                if remainder.upper() != "NONE" and remainder:
                    missing_cases.append(remainder)
            elif upper.startswith("REASONING:"):
                section = "reasoning"
                remainder = stripped[10:].strip()
                if remainder:
                    reasoning = remainder
            elif upper.startswith("SUGGESTIONS:") or upper.startswith("SUGGESTION:"):
                section = "suggestions"
                remainder = stripped.split(":", 1)[1].strip()
                if remainder.upper() != "NONE" and remainder:
                    suggestions.append(remainder)
            elif section == "counterexample" and stripped:
                counterexample += "\n" + stripped
            elif section == "missing" and stripped:
                clean = stripped.lstrip("-").lstrip("*").strip()
                if clean and clean.upper() != "NONE":
                    missing_cases.append(clean)
            elif section == "reasoning":
                reasoning += "\n" + stripped if reasoning else stripped
            elif section == "suggestions" and stripped:
                clean = stripped.lstrip("-").lstrip("*").strip()
                if clean and clean.upper() != "NONE":
                    suggestions.append(clean)

        has_counterexample = bool(counterexample.strip())

        if verdict == "PASS" and (has_counterexample or missing_cases):
            verdict = "UNCERTAIN"

        return FalsifyResult(
            verdict=verdict,
            has_counterexample=has_counterexample,
            counterexample=counterexample.strip(),
            missing_cases=missing_cases,
            python_checks=python_checks,
            reasoning=reasoning.strip(),
            suggestions=suggestions,
        )
