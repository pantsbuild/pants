# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import cast

from pants.backend.python.goals.lockfile import PythonLockfileRequest, PythonToolLockfileSentinel
from pants.backend.python.lint.flake8.skip_field import SkipFlake8Field
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    ConsoleScript,
    InterpreterConstraintsField,
    PythonSourceField,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import AllTargets, AllTargetsRequest, FieldSet, Target
from pants.engine.unions import UnionRule
from pants.option.custom_types import file_option, shell_str
from pants.util.docutil import git_url
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class Flake8FieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipFlake8Field).value


class Flake8(PythonToolBase):
    options_scope = "flake8"
    help = "The Flake8 Python linter (https://flake8.pycqa.org/)."

    default_version = "flake8>=3.9.2,<4.0"
    default_main = ConsoleScript("flake8")

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.flake8", "lockfile.txt")
    default_lockfile_path = "src/python/pants/backend/python/lint/flake8/lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=f"Don't use Flake8 when running `{register.bootstrap.pants_bin_name} lint`",
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=(
                "Arguments to pass directly to Flake8, e.g. "
                f'`--{cls.options_scope}-args="--ignore E123,W456 --enable-extensions H111"`'
            ),
        )
        register(
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help=(
                "Path to an INI config file understood by Flake8 "
                "(https://flake8.pycqa.org/en/latest/user/configuration.html).\n\n"
                f"Setting this option will disable `[{cls.options_scope}].config_discovery`. Use "
                f"this option if the config is located in a non-standard location."
            ),
        )
        register(
            "--config-discovery",
            type=bool,
            default=True,
            advanced=True,
            help=(
                "If true, Pants will include any relevant config files during "
                "runs (`.flake8`, `flake8`, `setup.cfg`, and `tox.ini`)."
                f"\n\nUse `[{cls.options_scope}].config` instead if your config is in a "
                f"non-standard location."
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
        # See https://flake8.pycqa.org/en/latest/user/configuration.html#configuration-locations
        # for how Flake8 discovers config files.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=cast(bool, self.options.config_discovery),
            check_existence=["flake8", ".flake8"],
            check_content={"setup.cfg": b"[flake8]", "tox.ini": b"[flake8]"},
        )


class Flake8LockfileSentinel(PythonToolLockfileSentinel):
    options_scope = Flake8.options_scope


@rule(
    desc=(
        "Determine all Python interpreter versions used by Flake8 in your project (for lockfile "
        "usage)"
    ),
    level=LogLevel.DEBUG,
)
async def setup_flake8_lockfile(
    _: Flake8LockfileSentinel, flake8: Flake8, python_setup: PythonSetup
) -> PythonLockfileRequest:
    if not flake8.uses_lockfile:
        return PythonLockfileRequest.from_tool(flake8)

    # While Flake8 will run in partitions, we need a single lockfile that works with every
    # partition.
    #
    # This ORs all unique interpreter constraints. The net effect is that every possible Python
    # interpreter used will be covered.
    all_tgts = await Get(AllTargets, AllTargetsRequest())
    unique_constraints = {
        InterpreterConstraints.create_from_targets([tgt], python_setup)
        for tgt in all_tgts
        if Flake8FieldSet.is_applicable(tgt)
    }
    constraints = InterpreterConstraints(itertools.chain.from_iterable(unique_constraints))
    return PythonLockfileRequest.from_tool(
        flake8, constraints or InterpreterConstraints(python_setup.interpreter_constraints)
    )


def rules():
    return (*collect_rules(), UnionRule(PythonToolLockfileSentinel, Flake8LockfileSentinel))
