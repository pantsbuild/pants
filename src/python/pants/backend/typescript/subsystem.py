# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolBase
from pants.option.option_types import SkipOption


class TypeScriptSubsystem(NodeJSToolBase):
    options_scope = "typescript"
    name = "TypeScript"
    help = """TypeScript type checker (tsc)."""

    # NOTE: TypeScript always uses resolve-based execution (not download-and-execute)
    # because it needs access to project dependencies for type checking.
    # The resolve is determined dynamically in check.py using ChosenNodeResolve.
    # The actual TypeScript version comes from the project's package.json dependencies.
    default_version = "typescript@9.9.9"

    skip = SkipOption("check")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Override binary name since the package is 'typescript' but the binary is 'tsc'
        self._binary_name_override = "tsc"

    @property
    def binary_name(self) -> str:
        """The binary name to run for this tool."""
        return self._binary_name_override or super().binary_name
