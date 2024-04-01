# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.engine.unions import union
from pants.util.strutil import softwrap


@union
class ExportableTool:
    """Mark a subsystem as exportable.

    Using this class has 2 parts:
    - The tool class should subclass this.
      This can be done at the language-backend level, for example, `PythonToolRequirementsBase`.
      The help message can be extended with instructions specific to that tool or language backend
    - Each exportable tool should have a `UnionRule` to `ExportableTool`.
      This `UnionRule` is what ties the class into the export machinery.
    """

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
