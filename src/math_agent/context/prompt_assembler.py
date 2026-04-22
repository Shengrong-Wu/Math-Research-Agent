"""Prompt assembly helpers with graded degradation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class PromptVariant:
    name: str
    content: str


@dataclass(frozen=True)
class PromptSection:
    name: str
    variants: list[PromptVariant]
    priority: int = 0


@dataclass
class AssemblyResult:
    text: str
    chars: int
    selected_variants: dict[str, str] = field(default_factory=dict)
    section_char_counts: dict[str, int] = field(default_factory=dict)
    dropped_sections: list[str] = field(default_factory=list)
    near_limit: bool = False

    @property
    def profile(self) -> str:
        return ",".join(
            f"{name}:{variant}" for name, variant in self.selected_variants.items()
        )


class PromptAssembler:
    """Greedily fit the richest prompt variant under a character budget."""

    def __init__(self, *, near_limit_ratio: float = 0.9) -> None:
        self.near_limit_ratio = near_limit_ratio

    def fit(
        self,
        sections: list[PromptSection],
        *,
        builder: Callable[[dict[str, str]], str],
        max_chars: int,
        degrade_bias: int = 0,
    ) -> AssemblyResult:
        if max_chars <= 0:
            return AssemblyResult(text="", chars=0)

        indices = {section.name: 0 for section in sections}
        for _ in range(max(0, degrade_bias)):
            degraded = self._degrade_once(sections, indices)
            if not degraded:
                break

        while True:
            selected = {
                section.name: section.variants[indices[section.name]].content
                for section in sections
            }
            text = builder(selected)
            chars = len(text)
            if chars <= max_chars:
                selected_variants = {
                    section.name: section.variants[indices[section.name]].name
                    for section in sections
                }
                section_char_counts = {
                    name: len(content) for name, content in selected.items() if content
                }
                dropped_sections = [
                    section.name for section in sections if not selected.get(section.name)
                ]
                return AssemblyResult(
                    text=text,
                    chars=chars,
                    selected_variants=selected_variants,
                    section_char_counts=section_char_counts,
                    dropped_sections=dropped_sections,
                    near_limit=chars >= int(max_chars * self.near_limit_ratio),
                )
            if not self._degrade_once(sections, indices):
                truncated = text[:max_chars]
                selected_variants = {
                    section.name: section.variants[indices[section.name]].name
                    for section in sections
                }
                return AssemblyResult(
                    text=truncated,
                    chars=len(truncated),
                    selected_variants=selected_variants,
                    section_char_counts={
                        name: len(content) for name, content in selected.items() if content
                    },
                    dropped_sections=[
                        section.name
                        for section in sections
                        if not selected.get(section.name)
                    ],
                    near_limit=True,
                )

    @staticmethod
    def _degrade_once(
        sections: list[PromptSection],
        indices: dict[str, int],
    ) -> bool:
        candidates = [
            section
            for section in sections
            if indices[section.name] < len(section.variants) - 1
        ]
        if not candidates:
            return False
        candidates.sort(
            key=lambda section: (
                section.priority,
                len(section.variants) - indices[section.name],
                section.name,
            )
        )
        target = candidates[0]
        indices[target.name] += 1
        return True
