# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from dataclasses import dataclass

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.lint.bandit.skip_field import SkipBanditField
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    ConsoleScript,
    InterpreterConstraintsField,
    PythonSourceField,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import AllTargets, AllTargetsRequest, FieldSet, Target
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, FileOption, SkipOption
from pants.util.docutil import git_url
from pants.util.logging import LogLevel


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
    config = FileOption(
        "--config",
        default=None,
        advanced=True,
        help=(
            "Path to a Bandit YAML config file "
            "(https://bandit.readthedocs.io/en/latest/config.html)."
        ),
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
    desc=(
        "Determine all Python interpreter versions used by Bandit in your project (for lockfile "
        "usage)"
    ),
    level=LogLevel.DEBUG,
)
async def setup_bandit_lockfile(
    _: BanditLockfileSentinel, bandit: Bandit, python_setup: PythonSetup
) -> GeneratePythonLockfile:
    if not bandit.uses_lockfile:
        return GeneratePythonLockfile.from_tool(
            bandit, use_pex=python_setup.generate_lockfiles_with_pex
        )

    # While Bandit will run in partitions, we need a single lockfile that works with every
    # partition.
    #
    # This ORs all unique interpreter constraints. The net effect is that every possible Python
    # interpreter used will be covered.
    all_tgts = await Get(AllTargets, AllTargetsRequest())
    unique_constraints = {
        InterpreterConstraints.create_from_targets([tgt], python_setup)
        for tgt in all_tgts
        if BanditFieldSet.is_applicable(tgt)
    }
    constraints = InterpreterConstraints(itertools.chain.from_iterable(unique_constraints))
    return GeneratePythonLockfile.from_tool(
        bandit,
        constraints or InterpreterConstraints(python_setup.interpreter_constraints),
        use_pex=python_setup.generate_lockfiles_with_pex,
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, BanditLockfileSentinel),
    )
