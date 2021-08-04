# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from typing import cast

from pants.backend.experimental.python.lockfile import (
    PythonLockfileRequest,
    PythonToolLockfileSentinel,
)
from pants.backend.python.lint.bandit.skip_field import SkipBanditField
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript, InterpreterConstraintsField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import UnexpandedTargets
from pants.engine.unions import UnionRule
from pants.option.custom_types import file_option, shell_str
from pants.python.python_setup import PythonSetup
from pants.util.docutil import git_url
from pants.util.logging import LogLevel


class Bandit(PythonToolBase):
    options_scope = "bandit"
    help = "A tool for finding security issues in Python code (https://bandit.readthedocs.io)."

    default_version = "bandit>=1.7.0,<1.8"
    default_extra_requirements = [
        "setuptools<45; python_full_version == '2.7.*'",
        "setuptools; python_version > '2.7'",
        "stevedore<3",  # stevedore 3.0 breaks Bandit.
    ]
    default_main = ConsoleScript("bandit")

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.bandit", "lockfile.txt")
    default_lockfile_path = "src/python/pants/backend/python/lint/bandit/lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=f"Don't use Bandit when running `{register.bootstrap.pants_bin_name} lint`",
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=(
                f"Arguments to pass directly to Bandit, e.g. "
                f'`--{cls.options_scope}-args="--skip B101,B308 --confidence"`'
            ),
        )
        register(
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help=(
                "Path to a Bandit YAML config file "
                "(https://bandit.readthedocs.io/en/latest/config.html)."
            ),
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> tuple[str, ...]:
        return tuple(self.options.args)

    @property
    def config(self) -> str | None:
        return cast("str | None", self.options.config)

    @property
    def config_request(self) -> ConfigFilesRequest:
        # Refer to https://bandit.readthedocs.io/en/latest/config.html. Note that there are no
        # default locations for Bandit config files.
        return ConfigFilesRequest(
            specified=self.config, specified_option_name=f"{self.options_scope}.config"
        )


class BanditLockfileSentinel(PythonToolLockfileSentinel):
    pass


@rule(
    desc="Determine all Python interpreter versions used by Bandit in your project",
    level=LogLevel.DEBUG,
)
async def setup_bandit_lockfile(
    _: BanditLockfileSentinel, bandit: Bandit, python_setup: PythonSetup
) -> PythonLockfileRequest:
    if python_setup.disable_mixed_interpreter_constraints:
        constraints = InterpreterConstraints(python_setup.interpreter_constraints)
    else:
        all_build_targets = await Get(UnexpandedTargets, AddressSpecs([DescendantAddresses("")]))
        unique_constraints = {
            InterpreterConstraints.create_from_compatibility_fields(
                [tgt[InterpreterConstraintsField]], python_setup
            )
            for tgt in all_build_targets
            if tgt.has_field(InterpreterConstraintsField) and not tgt.get(SkipBanditField).value
        }
        constraints = InterpreterConstraints(itertools.chain.from_iterable(unique_constraints))

    return PythonLockfileRequest.from_tool(
        bandit, constraints or InterpreterConstraints(python_setup.interpreter_constraints)
    )


def rules():
    return (*collect_rules(), UnionRule(PythonToolLockfileSentinel, BanditLockfileSentinel))
