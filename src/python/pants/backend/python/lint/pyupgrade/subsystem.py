# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.goals.lockfile import (
    GeneratePythonLockfile,
    GeneratePythonToolLockfileSentinel,
)
from pants.backend.python.subsystems.python_tool_base import ExportToolOption, PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import ConsoleScript
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, SkipOption
from pants.util.docutil import git_url


class PyUpgrade(PythonToolBase):
    options_scope = "pyupgrade"
    name = "pyupgrade"
    help = (
        "Upgrade syntax for newer versions of the language (https://github.com/asottile/pyupgrade)."
    )

    default_version = "pyupgrade>=2.33.0,<2.35"
    default_main = ConsoleScript("pyupgrade")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.pyupgrade", "pyupgrade.lock")
    default_lockfile_path = "src/python/pants/backend/python/lint/pyupgrade/pyupgrade.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--py39-plus --keep-runtime-typing")
    export = ExportToolOption()


class PyUpgradeLockfileSentinel(GeneratePythonToolLockfileSentinel):
    resolve_name = PyUpgrade.options_scope


@rule
def setup_pyupgrade_lockfile(
    _: PyUpgradeLockfileSentinel, pyupgrade: PyUpgrade, python_setup: PythonSetup
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(
        pyupgrade, use_pex=python_setup.generate_lockfiles_with_pex
    )


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
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, PyUpgradeLockfileSentinel),
        UnionRule(ExportPythonToolSentinel, PyUpgradeExportSentinel),
    )
