from math_agent.context.prompt_assembler import (
    PromptAssembler,
    PromptSection,
    PromptVariant,
)


def test_prompt_assembler_degrades_low_priority_sections_first():
    assembler = PromptAssembler()
    result = assembler.fit(
        [
            PromptSection(
                name="core",
                priority=3,
                variants=[
                    PromptVariant("full", "A" * 40),
                    PromptVariant("compact", "A" * 20),
                ],
            ),
            PromptSection(
                name="optional",
                priority=1,
                variants=[
                    PromptVariant("full", "B" * 40),
                    PromptVariant("none", ""),
                ],
            ),
        ],
        builder=lambda selected: "\n".join(
            part for part in [selected["core"], selected["optional"]] if part
        ),
        max_chars=50,
    )

    assert result.selected_variants["optional"] == "none"
    assert result.selected_variants["core"] == "full"
    assert result.chars <= 50
