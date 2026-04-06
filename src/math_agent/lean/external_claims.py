"""External claim (axiom) management for Lean 4 proofs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExternalClaim:
    name: str
    lean_type: str
    justification: str


class ExternalClaimRegistry:
    """Registry of external claims declared as Lean axioms.

    External claims represent results that are assumed without proof
    inside the formalisation -- for example standard textbook results
    whose full proof would be out of scope.
    """

    def __init__(self) -> None:
        self._claims: dict[str, ExternalClaim] = {}

    def add(self, name: str, lean_type: str, justification: str) -> None:
        """Register an external claim.

        Parameters
        ----------
        name:
            The axiom identifier used in Lean code.
        lean_type:
            The Lean type signature of the axiom
            (e.g. ``"(n : Nat) -> n + 0 = n"``).
        justification:
            Human-readable reason why this axiom is acceptable
            (e.g. *"standard textbook result"*).
        """
        self._claims[name] = ExternalClaim(
            name=name,
            lean_type=lean_type,
            justification=justification,
        )

    def remove(self, name: str) -> None:
        """Remove a previously registered external claim."""
        del self._claims[name]

    def list_claims(self) -> list[ExternalClaim]:
        """Return all registered claims in insertion order."""
        return list(self._claims.values())

    def to_lean(self) -> str:
        """Generate Lean 4 code declaring all external claims as axioms.

        Each axiom is preceded by a doc-comment containing its
        justification so that reviewers can audit why it was introduced.
        """
        if not self._claims:
            return "-- No external claims registered.\n"

        lines: list[str] = [
            "/-! # External Claims",
            "",
            "The following axioms are assumed without proof.",
            "-/",
            "",
        ]
        for claim in self._claims.values():
            lines.append(f"/-- External claim: {claim.justification} -/")
            lines.append(f"axiom {claim.name} : {claim.lean_type}")
            lines.append("")

        return "\n".join(lines)

    def count(self) -> int:
        """Return the number of registered external claims."""
        return len(self._claims)
