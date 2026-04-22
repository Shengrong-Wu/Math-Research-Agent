"""Search the installed Mathlib source for API names and signatures.

This gives the CLI agent access to the *actual* API surface of whatever
Mathlib version is pinned in the current workspace — not training-data
guesses from a different version.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SearchHit:
    """A single Mathlib search result."""

    qualified_name: str  # e.g., "IsLocalRing.maximalIdeal"
    kind: str  # theorem | lemma | def | class | structure | instance | axiom
    file: str  # relative path inside Mathlib
    line: int
    signature: str  # first line of the declaration (truncated)


async def search_mathlib(
    workspace: Path,
    query: str,
    *,
    max_results: int = 20,
) -> list[SearchHit]:
    """Grep the installed Mathlib source for declarations matching *query*.

    Searches ``theorem``, ``lemma``, ``def``, ``class``, ``structure``,
    ``instance``, and ``axiom`` declarations whose name contains *query*
    (case-insensitive).

    Args:
        workspace: Lean project root (must have ``.lake/packages/mathlib``).
        query: Search term (e.g., ``"maximalIdeal"``, ``"Nakayama"``).
        max_results: Cap on returned hits.

    Returns:
        List of :class:`SearchHit` sorted by relevance (exact substring
        match in the name first, then file path length as tie-breaker).
    """
    mathlib_dir = workspace / ".lake" / "packages" / "mathlib"
    if not mathlib_dir.is_dir():
        logger.warning("Mathlib source not found at %s", mathlib_dir)
        return []

    # Build a regex that matches Lean 4 declarations containing the query
    # in the declared name.
    safe_q = re.escape(query)
    pattern = (
        r"^(theorem|lemma|def|class|structure|instance|axiom|abbrev)\s+"
        r"(\S*" + safe_q + r"\S*)"
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "grep",
            "-rn",
            "-i",
            "--include=*.lean",
            "-E",
            pattern,
            str(mathlib_dir / "Mathlib"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, _ = await proc.communicate()
    except FileNotFoundError:
        logger.warning("grep not found; cannot search Mathlib")
        return []

    hits: list[SearchHit] = []
    for raw_line in stdout_bytes.decode(errors="replace").splitlines():
        # Format: filepath:lineno:matched_line
        parts = raw_line.split(":", 2)
        if len(parts) < 3:
            continue
        filepath, lineno_str, matched = parts[0], parts[1], parts[2]

        try:
            lineno = int(lineno_str)
        except ValueError:
            continue

        m = re.match(
            r"(theorem|lemma|def|class|structure|instance|axiom|abbrev)\s+(\S+)",
            matched.strip(),
        )
        if not m:
            continue

        kind = m.group(1)
        name = m.group(2).rstrip(":")  # strip trailing colon if present

        # Relative path from Mathlib root
        try:
            rel = Path(filepath).relative_to(mathlib_dir)
        except ValueError:
            rel = Path(filepath)

        hits.append(
            SearchHit(
                qualified_name=name,
                kind=kind,
                file=str(rel),
                line=lineno,
                signature=matched.strip()[:200],
            )
        )

        if len(hits) >= max_results * 3:
            break  # pre-cap before sorting

    # Sort: exact substring in name first, then shorter file path
    def _sort_key(h: SearchHit) -> tuple[int, int]:
        exact = 0 if query.lower() in h.qualified_name.lower() else 1
        return (exact, len(h.file))

    hits.sort(key=_sort_key)
    return hits[:max_results]


async def search_mathlib_for_type(
    workspace: Path,
    type_fragment: str,
    *,
    max_results: int = 10,
) -> list[SearchHit]:
    """Search Mathlib for declarations whose *type signature* contains
    the given fragment (e.g., ``"jacobson"``, ``"FG"``).

    This is slower than name search because it greps the full line, but
    useful when the name is unknown and only the type shape is known.
    """
    mathlib_dir = workspace / ".lake" / "packages" / "mathlib"
    if not mathlib_dir.is_dir():
        return []

    safe_q = re.escape(type_fragment)

    try:
        proc = await asyncio.create_subprocess_exec(
            "grep",
            "-rn",
            "-i",
            "--include=*.lean",
            "-E",
            r"^(theorem|lemma|def)\s+\S+.*" + safe_q,
            str(mathlib_dir / "Mathlib"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, _ = await proc.communicate()
    except FileNotFoundError:
        return []

    hits: list[SearchHit] = []
    for raw_line in stdout_bytes.decode(errors="replace").splitlines():
        parts = raw_line.split(":", 2)
        if len(parts) < 3:
            continue
        filepath, lineno_str, matched = parts[0], parts[1], parts[2]

        try:
            lineno = int(lineno_str)
        except ValueError:
            continue

        m = re.match(r"(theorem|lemma|def)\s+(\S+)", matched.strip())
        if not m:
            continue

        kind = m.group(1)
        name = m.group(2).rstrip(":")

        try:
            rel = Path(filepath).relative_to(mathlib_dir)
        except ValueError:
            rel = Path(filepath)

        hits.append(
            SearchHit(
                qualified_name=name,
                kind=kind,
                file=str(rel),
                line=lineno,
                signature=matched.strip()[:200],
            )
        )

        if len(hits) >= max_results * 3:
            break

    hits.sort(key=lambda h: len(h.file))
    return hits[:max_results]


def format_search_results(hits: list[SearchHit]) -> str:
    """Format search results into a string suitable for LLM context."""
    if not hits:
        return "(no results)"
    lines: list[str] = []
    for h in hits:
        lines.append(f"  {h.kind} {h.qualified_name}")
        lines.append(f"    file: {h.file}:{h.line}")
        if h.signature != f"{h.kind} {h.qualified_name}":
            lines.append(f"    sig:  {h.signature}")
    return "\n".join(lines)
