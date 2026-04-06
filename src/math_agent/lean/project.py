"""Lean project scaffolding -- lakefile, toolchain, and module management."""

from __future__ import annotations

import re
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
    # Mathlib version tag derived from toolchain
    # ------------------------------------------------------------------

    @property
    def _mathlib_rev(self) -> str:
        """Extract a Mathlib-compatible version tag from the toolchain string.

        ``leanprover/lean4:v4.28.0`` → ``v4.28.0``.
        Falls back to ``master`` if the pattern doesn't match.
        """
        m = re.search(r"v[\d]+\.[\d]+\.[\d]+", self.toolchain)
        return m.group(0) if m else "master"

    # ------------------------------------------------------------------
    # Project initialisation
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Create *lakefile.toml*, *lean-toolchain*, and the
        ``MathAgent/`` source directory if they do not already exist.
        """
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._module_dir.mkdir(parents=True, exist_ok=True)

        # Prefer lakefile.toml; also accept legacy lakefile.lean
        lakefile_toml = self.workspace / "lakefile.toml"
        lakefile_lean = self.workspace / "lakefile.lean"
        if not lakefile_toml.exists() and not lakefile_lean.exists():
            lakefile_toml.write_text(self._generate_lakefile_toml())

        toolchain_file = self.workspace / "lean-toolchain"
        if not toolchain_file.exists():
            toolchain_file.write_text(self.toolchain + "\n")

    # ------------------------------------------------------------------
    # Module helpers
    # ------------------------------------------------------------------

    def add_module(self, name: str, content: str) -> Path:
        """Write a ``.lean`` file to ``MathAgent/{name}.lean``, update
        the root import file, and return the module path.
        """
        path = self._module_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        self._update_root_import()
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
        """Write *content* to ``MathAgent/{name}.lean`` and refresh the
        root import file.
        """
        path = self._module_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        self._update_root_import()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _module_path(self, name: str) -> Path:
        return self._module_dir / f"{name}.lean"

    def _update_root_import(self) -> None:
        """Write (or overwrite) ``MathAgent.lean`` at the workspace root.

        This file simply imports every module under ``MathAgent/``, which
        is required by Lake to build the ``MathAgent`` library target.
        """
        modules = self.list_modules()
        lines = [
            "-- Auto-generated root import file. Do not edit manually.",
        ]
        for mod in modules:
            lines.append(f"import MathAgent.{mod}")
        lines.append("")
        root = self.workspace / "MathAgent.lean"
        root.write_text("\n".join(lines))

    def _generate_lakefile_toml(self) -> str:
        """Generate a ``lakefile.toml`` with Mathlib pinned to the
        toolchain version tag.
        """
        lines = [
            'name = "mathAgent"',
            'version = "0.1.0"',
            'keywords = ["math"]',
            'defaultTargets = ["MathAgent"]',
            "",
            "[leanOptions]",
            "autoImplicit = false",
            "relaxedAutoImplicit = false",
            "",
        ]

        if self.use_mathlib:
            rev = self._mathlib_rev
            lines += [
                "[[require]]",
                'name = "mathlib"',
                'scope = "leanprover-community"',
                f'rev = "{rev}"',
                "",
            ]

        lines += [
            "[[lean_lib]]",
            'name = "MathAgent"',
            "",
        ]
        return "\n".join(lines)
