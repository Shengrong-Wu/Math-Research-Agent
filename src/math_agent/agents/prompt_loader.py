"""Helpers for loading prompt sections from bundled markdown files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

_PROMPTS_ROOT = Path(__file__).parent / "prompts"
_SECTION_RE = re.compile(r"^<!-- SECTION: ([a-z0-9_]+) -->\s*$")


@lru_cache(maxsize=None)
def load_prompt_bundle(name: str) -> dict[str, str]:
    """Return a mapping of section name -> prompt text for *name*.

    The bundle format is a markdown file split by explicit section markers:

    ``<!-- SECTION: section_name -->``
    """

    path = _PROMPTS_ROOT / f"{name}.md"
    text = path.read_text(encoding="utf-8")

    sections: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []

    for line in text.splitlines():
        match = _SECTION_RE.match(line)
        if match:
            if current is not None:
                sections[current] = "\n".join(lines).strip() + "\n"
            current = match.group(1)
            lines = []
            continue
        lines.append(line)

    if current is not None:
        sections[current] = "\n".join(lines).strip() + "\n"

    if not sections:
        raise ValueError(f"No prompt sections found in {path}")
    return sections


def load_prompt_section(bundle: str, section: str) -> str:
    """Load a single prompt section from *bundle*."""

    sections = load_prompt_bundle(bundle)
    try:
        return sections[section]
    except KeyError as exc:
        available = ", ".join(sorted(sections))
        raise KeyError(f"Unknown prompt section {section!r}. Available: {available}") from exc


def render_prompt_section(bundle: str, section: str, **kwargs: object) -> str:
    """Render a prompt section with ``str.format`` substitution."""

    return load_prompt_section(bundle, section).format(**kwargs)
