# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
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


class AddTrailingComma(PythonToolBase):
    options_scope = "add-trailing-comma"
    name = "add-trailing-comma"
    help = "The add-trailing-comma Python code formatter (https://github.com/asottile/add-trailing-comma)."

    default_version = "add-trailing-comma>=2.2.3,<3"
    default_main = ConsoleScript("add-trailing-comma")
    default_requirements = [default_version]

    register_interpreter_constraints = True

    default_lockfile_resource = (
        "pants.backend.python.lint.add_trailing_comma",
        "add_trailing_comma.lock",
    )
    lockfile_rules_type = LockfileRules.SIMPLE

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--py36-plus")
    export = ExportToolOption()


class AddTrailingCommaExportSentinel(ExportPythonToolSentinel):
    pass


@rule
def add_trailing_comma_export(
    _: AddTrailingCommaExportSentinel,
    add_trailing_comma: AddTrailingComma,
) -> ExportPythonTool:
    if not add_trailing_comma.export:
        return ExportPythonTool(resolve_name=add_trailing_comma.options_scope, pex_request=None)
    return ExportPythonTool(
        resolve_name=add_trailing_comma.options_scope,
        pex_request=add_trailing_comma.to_pex_request(),
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(ExportPythonToolSentinel, AddTrailingCommaExportSentinel),
    )
