"""Split a complete proof into logical Lean modules."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ModulePlan:
    name: str
    description: str
    dependencies: list[str] = field(default_factory=list)
    proof_fragment: str = ""


class ModuleSplitter:
    """Heuristically split a monolithic Lean proof into modules."""

    # Patterns that mark top-level declaration boundaries.
    _DECL_RE = re.compile(
        r"^(theorem|lemma|def|noncomputable\s+def|instance|structure|inductive|class)\s+"
        r"(?P<name>\S+)",
        re.MULTILINE,
    )

    def __init__(self) -> None:
        pass

    def split(
        self,
        proof: str,
        module_names: list[str] | None = None,
    ) -> list[ModulePlan]:
        """Split *proof* into logical modules.

        If *module_names* is not provided the splitter auto-detects
        boundaries by looking for top-level ``lemma`` / ``theorem``
        declarations.

        Each returned :class:`ModulePlan` contains the fragment of the
        proof text it covers together with a best-effort dependency list
        (other module names whose declarations are referenced).
        """
        # Collect all top-level declarations with their positions.
        declarations = self._find_declarations(proof)

        if not declarations:
            # Nothing to split -- return the whole proof as one module.
            name = (module_names or ["Main"])[0]
            return [
                ModulePlan(
                    name=name,
                    description="Complete proof (no splittable declarations found)",
                    dependencies=[],
                    proof_fragment=proof,
                )
            ]

        # Build fragments: each fragment runs from one declaration start
        # to the next.
        fragments: list[tuple[str, str]] = []  # (decl_name, text)
        for idx, (start, decl_name) in enumerate(declarations):
            end = declarations[idx + 1][0] if idx + 1 < len(declarations) else len(proof)
            fragment_text = proof[start:end].rstrip()
            fragments.append((decl_name, fragment_text))

        # Handle any preamble (imports, opens, etc.) that appear before
        # the first declaration.
        preamble = proof[: declarations[0][0]].strip()

        # If the caller supplied explicit module names, map fragments
        # round-robin; otherwise derive names from declarations.
        if module_names is not None:
            assigned_names = [
                module_names[i % len(module_names)]
                for i in range(len(fragments))
            ]
        else:
            assigned_names = [self._sanitise_name(n) for _, (n, _) in enumerate(fragments)]

        # Build ModulePlans with dependency detection.
        plans: list[ModulePlan] = []
        all_decl_names = [name for (name, _) in fragments]

        for i, (mod_name, (decl_name, text)) in enumerate(
            zip(assigned_names, fragments)
        ):
            full_text = (preamble + "\n\n" + text).strip() if preamble else text

            # Detect which *other* declarations are referenced in this
            # fragment (simple heuristic: look for their names).
            deps: list[str] = []
            for j, other_decl in enumerate(all_decl_names):
                if j == i:
                    continue
                if re.search(r"\b" + re.escape(other_decl) + r"\b", text):
                    dep_mod = assigned_names[j]
                    if dep_mod not in deps:
                        deps.append(dep_mod)

            plans.append(
                ModulePlan(
                    name=mod_name,
                    description=f"Contains declaration: {decl_name}",
                    dependencies=deps,
                    proof_fragment=full_text,
                )
            )

        return plans

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_declarations(self, proof: str) -> list[tuple[int, str]]:
        """Return ``(start_position, declaration_name)`` pairs."""
        results: list[tuple[int, str]] = []
        for m in self._DECL_RE.finditer(proof):
            results.append((m.start(), m.group("name")))
        return results

    @staticmethod
    def _sanitise_name(name: str) -> str:
        """Turn a Lean identifier into a valid module file name."""
        # Remove namespace prefixes (keep last segment).
        name = name.rsplit(".", maxsplit=1)[-1]
        # Replace non-alphanumeric chars with underscores.
        name = re.sub(r"[^A-Za-z0-9_]", "_", name)
        # Capitalise the first character for Lean module conventions.
        if name and name[0].islower():
            name = name[0].upper() + name[1:]
        return name or "Module"
