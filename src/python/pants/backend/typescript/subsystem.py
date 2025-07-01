# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolBase
from pants.option.option_types import SkipOption, StrListOption
from pants.util.strutil import softwrap


class TypeScriptSubsystem(NodeJSToolBase):
    options_scope = "typescript"
    name = "TypeScript"
    help = """TypeScript type checker (tsc)."""

    default_version = "typescript@5.8.2"

    skip = SkipOption("check")

    output_dirs = StrListOption(
        default=[],
        advanced=True,
        help=softwrap(
            """
            Override output directories to cache for incremental TypeScript builds.

            If specified, these directories replace the default patterns entirely.
            If empty, uses common patterns: dist, build, lib, out, compiled, bundles.

            Example: ["my-custom-output", "generated-types"]
            """
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Override binary name since the package is 'typescript' but the binary is 'tsc'
        self._binary_name_override = "tsc"

    @property
    def binary_name(self) -> str:
        """The binary name to run for this tool."""
        return self._binary_name_override or super().binary_name
