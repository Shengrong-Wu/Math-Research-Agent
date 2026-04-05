"""Lean project scaffolding -- lakefile, toolchain, and module management."""

from __future__ import annotations

from pathlib import Path


class LeanProject:
    """Create and manage a Lean 4 / Lake project on disk."""

    def __init__(
        self,
        workspace: Path,
        toolchain: str,
        use_mathlib: bool = True,
    ) -> None:
        self.workspace = workspace
        self.toolchain = toolchain
        self.use_mathlib = use_mathlib
        self._module_dir = workspace / "MathAgent"

    # ------------------------------------------------------------------
    # Project initialisation
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Create *lakefile.lean*, *lean-toolchain*, and the
        ``MathAgent/`` source directory if they do not already exist.
        """
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._module_dir.mkdir(parents=True, exist_ok=True)

        lakefile = self.workspace / "lakefile.lean"
        if not lakefile.exists():
            lakefile.write_text(self._generate_lakefile())

        toolchain_file = self.workspace / "lean-toolchain"
        if not toolchain_file.exists():
            toolchain_file.write_text(self.toolchain + "\n")

    # ------------------------------------------------------------------
    # Module helpers
    # ------------------------------------------------------------------

    def add_module(self, name: str, content: str) -> Path:
        """Write a ``.lean`` file to ``MathAgent/{name}.lean`` and return
        its path.
        """
        path = self._module_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def list_modules(self) -> list[str]:
        """Return the names of all ``.lean`` files under ``MathAgent/``
        (without the ``.lean`` extension).
        """
        if not self._module_dir.exists():
            return []
        return sorted(
            p.stem for p in self._module_dir.glob("*.lean")
        )

    def read_module(self, name: str) -> str:
        """Read and return the content of ``MathAgent/{name}.lean``."""
        return self._module_path(name).read_text()

    def write_module(self, name: str, content: str) -> None:
        """Write *content* to ``MathAgent/{name}.lean``."""
        path = self._module_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _module_path(self, name: str) -> Path:
        return self._module_dir / f"{name}.lean"

    def _generate_lakefile(self) -> str:
        lines: list[str] = [
            'import Lake',
            'open Lake DSL',
            '',
            'package mathAgent where',
            '  leanOptions := #[',
            '    \u27e8`autoImplicit, false\u27e9',
            '  ]',
        ]

        if self.use_mathlib:
            lines += [
                '',
                'require mathlib from git',
                '  "https://github.com/leanprover-community/mathlib4"',
            ]

        lines += [
            '',
            '@[default_target]',
            'lean_lib MathAgent where',
            '  srcDir := "."',
            '',
        ]
        return "\n".join(lines)
