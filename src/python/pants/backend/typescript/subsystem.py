# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolBase
from pants.option.option_types import SkipOption, StrListOption, StrOption
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class TypeScriptSubsystem(NodeJSToolBase):
    options_scope = "typescript"
    name = "TypeScript"
    help = """TypeScript type checker (tsc)."""

    # TypeScript always uses resolve-based execution because it needs access to project
    # dependencies for type checking. The resolve is determined dynamically in check.py.
    # This default version is never used - TypeScript must come from project package.json.
    default_version = "typescript@FROM_PACKAGE_JSON"

    skip = SkipOption("check")

    # TODO: Do we still need this?
    cache_dir = StrOption(
        default="~/.cache/pants/typescript",
        help=(
            "Directory to use for TypeScript incremental compilation cache. "
            "TypeScript's --build mode generates .tsbuildinfo files and compiled outputs "
            "that enable incremental compilation on subsequent runs."
        ),
        advanced=True,
    )

    extra_build_args = StrListOption(
        default=["--verbose"],
        help=(
            "Extra arguments to pass to tsc when running in --build mode. "
            "These args are added to the base command 'tsc --build'. "
            "Commonly used: --verbose (default), --force, --dry."
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Warn if user manually set version
        if self.version != "typescript@FROM_PACKAGE_JSON":
            logger.warning(
                softwrap(f"""
                    You set --typescript-version={self.version}. This setting is ignored because
                    TypeScript always uses the version from your project's package.json dependencies
                    or devDependencies. Please ensure TypeScript is listed in your package.json.
                """)
            )

        self._binary_name_override = "tsc"

    @property
    def binary_name(self) -> str:
        """The binary name to run for this tool."""
        return self._binary_name_override or super().binary_name
