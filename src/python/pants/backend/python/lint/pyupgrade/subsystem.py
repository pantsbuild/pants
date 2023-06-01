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


class PyUpgrade(PythonToolBase):
    options_scope = "pyupgrade"
    name = "pyupgrade"
    help = (
        "Upgrade syntax for newer versions of the language (https://github.com/asottile/pyupgrade)."
    )

    default_version = "pyupgrade>=2.33.0,<4"
    default_main = ConsoleScript("pyupgrade")
    default_requirements = [default_version]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.lint.pyupgrade", "pyupgrade.lock")
    lockfile_rules_type = LockfileRules.SIMPLE

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--py39-plus --keep-runtime-typing")
    export = ExportToolOption()


class PyUpgradeExportSentinel(ExportPythonToolSentinel):
    pass


@rule
def pyupgrade_export(_: PyUpgradeExportSentinel, pyupgrade: PyUpgrade) -> ExportPythonTool:
    if not pyupgrade.export:
        return ExportPythonTool(resolve_name=pyupgrade.options_scope, pex_request=None)
    return ExportPythonTool(
        resolve_name=pyupgrade.options_scope, pex_request=pyupgrade.to_pex_request()
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(ExportPythonToolSentinel, PyUpgradeExportSentinel),
    )
