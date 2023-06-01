# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.subsystems.python_tool_base import (
    ExportToolOption,
    LockfileRules,
    PythonToolBase,
)
from pants.backend.python.target_types import ConsoleScript
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, SkipOption


class Autoflake(PythonToolBase):
    options_scope = "autoflake"
    name = "Autoflake"
    help = "The Autoflake Python code formatter (https://github.com/myint/autoflake)."

    default_version = "autoflake>=1.4,<3"
    default_main = ConsoleScript("autoflake")
    default_requirements = [default_version]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.lint.autoflake", "autoflake.lock")
    lockfile_rules_type = LockfileRules.SIMPLE

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(
        example="--remove-all-unused-imports --target-version=py37 --quiet",
        # This argument was previously hardcoded. Moved it a default argument
        # to allow it to be overridden while maintaining the existing api.
        # See: https://github.com/pantsbuild/pants/issues/16193
        default=["--remove-all-unused-imports"],
    )
    export = ExportToolOption()


class AutoflakeExportSentinel(ExportPythonToolSentinel):
    pass


@rule
def autoflake_export(_: AutoflakeExportSentinel, autoflake: Autoflake) -> ExportPythonTool:
    if not autoflake.export:
        return ExportPythonTool(resolve_name=autoflake.options_scope, pex_request=None)
    return ExportPythonTool(
        resolve_name=autoflake.options_scope, pex_request=autoflake.to_pex_request()
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(ExportPythonToolSentinel, AutoflakeExportSentinel),
    )
