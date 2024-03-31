# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.engine.unions import union
from pants.util.strutil import softwrap


@union
@dataclass(frozen=True)
class ExportableTool:
    """Mark a subsystem as exportable."""

    options_scope: str

    @classmethod
    def help_for_generate_lockfile_with_default_location(cls, resolve_name: str):
        """If this tool is configured to use the default lockfile, but a user requests to regenerate
        it, this help text will be shown to the user."""

        resolve = resolve_name
        return softwrap(
            f"""
            You requested to generate a lockfile for {resolve} because
            you included it in `--generate-lockfiles-resolve`, but
            {resolve} is a tool using its default lockfile.
        """
        )
