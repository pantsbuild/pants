# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.goals.resolves import ExportableTool
from pants.engine.rules import collect_rules
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, SkipOption


class Autoflake(PythonToolBase):
    options_scope = "autoflake"
    name = "Autoflake"
    help_short = "The Autoflake Python code formatter (https://github.com/myint/autoflake)."

    default_main = ConsoleScript("autoflake")
    default_requirements = ["autoflake>=1.4,<3"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.lint.autoflake", "autoflake.lock")

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(
        example="--remove-all-unused-imports --target-version=py37 --quiet",
        # This argument was previously hardcoded. Moved it a default argument
        # to allow it to be overridden while maintaining the existing api.
        # See: https://github.com/pantsbuild/pants/issues/16193
        default=["--remove-all-unused-imports"],
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(ExportableTool, Autoflake),
    ]
