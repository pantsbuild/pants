# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.lint.bandit.skip_field import SkipBanditField
from pants.backend.python.subsystems.python_tool_base import ExportToolOption, PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    ConsoleScript,
    InterpreterConstraintsField,
    PythonSourceField,
)
from pants.backend.python.util_rules.partition import _find_all_unique_interpreter_constraints
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, FileOption, SkipOption
from pants.util.docutil import git_url
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class BanditFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipBanditField).value


class Bandit(PythonToolBase):
    options_scope = "bandit"
    name = "Bandit"
    help = "A tool for finding security issues in Python code (https://bandit.readthedocs.io)."

    # When upgrading, check if Bandit has started using PEP 517 (a `pyproject.toml` file). If so,
    # remove `setuptools` from `default_extra_requirements`.
    default_version = "bandit>=1.7.0,<1.8"
    default_extra_requirements = [
        "setuptools",
        # GitPython 3.1.20 was yanked because it breaks Python 3.8+, but Poetry's lockfile
        # generation still tries to use it. Upgrade this to the newest version once released or
        # when switching away from Poetry.
        "GitPython==3.1.18",
    ]
    default_main = ConsoleScript("bandit")

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.bandit", "bandit.lock")
    default_lockfile_path = "src/python/pants/backend/python/lint/bandit/bandit.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    skip = SkipOption("lint")
    args = ArgsListOption(example="--skip B101,B308 --confidence")
    export = ExportToolOption()
    config = FileOption(
        "--config",
        default=None,
        advanced=True,
        help="Path to a Bandit YAML config file (https://bandit.readthedocs.io/en/latest/config.html).",
    )

    @property
    def config_request(self) -> ConfigFilesRequest:
        # Refer to https://bandit.readthedocs.io/en/latest/config.html. Note that there are no
        # default locations for Bandit config files.
        return ConfigFilesRequest(
            specified=self.config, specified_option_name=f"{self.options_scope}.config"
        )


class BanditLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = Bandit.options_scope


@rule(
    desc=softwrap(
        """
        Determine all Python interpreter versions used by Bandit in your project
        (for lockfile generation)
        """
    ),
    level=LogLevel.DEBUG,
)
async def setup_bandit_lockfile(
    _: BanditLockfileSentinel, bandit: Bandit, python_setup: PythonSetup
) -> GeneratePythonLockfile:
    if not bandit.uses_custom_lockfile:
        return GeneratePythonLockfile.from_tool(
            bandit, use_pex=python_setup.generate_lockfiles_with_pex
        )

    constraints = await _find_all_unique_interpreter_constraints(python_setup, BanditFieldSet)
    return GeneratePythonLockfile.from_tool(
        bandit,
        constraints,
        use_pex=python_setup.generate_lockfiles_with_pex,
    )


class BanditExportSentinel(ExportPythonToolSentinel):
    pass


@rule(
    desc=softwrap(
        """
        Determine all Python interpreter versions used by Bandit in your project
        (for `export` goal)
        """
    ),
    level=LogLevel.DEBUG,
)
async def bandit_export(
    _: BanditExportSentinel, bandit: Bandit, python_setup: PythonSetup
) -> ExportPythonTool:
    if not bandit.export:
        return ExportPythonTool(resolve_name=bandit.options_scope, pex_request=None)
    constraints = await _find_all_unique_interpreter_constraints(python_setup, BanditFieldSet)
    return ExportPythonTool(
        resolve_name=bandit.options_scope,
        pex_request=bandit.to_pex_request(interpreter_constraints=constraints),
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, BanditLockfileSentinel),
        UnionRule(ExportPythonToolSentinel, BanditExportSentinel),
    )
