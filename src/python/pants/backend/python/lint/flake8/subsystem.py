# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from typing import cast

from pants.backend.experimental.python.lockfile import (
    PythonLockfileRequest,
    PythonToolLockfileSentinel,
)
from pants.backend.python.lint.flake8.skip_field import SkipFlake8Field
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


class Flake8(PythonToolBase):
    options_scope = "flake8"
    help = "The Flake8 Python linter (https://flake8.pycqa.org/)."

    default_version = "flake8>=3.9.2,<4.0"
    default_extra_requirements = [
        "setuptools<45; python_full_version == '2.7.*'",
        "setuptools; python_version > '2.7'",
    ]
    default_main = ConsoleScript("flake8")

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.flake8", "lockfile.txt")
    default_lockfile_url = git_url("src/python/pants/backend/python/lint/flake8/lockfile.txt")

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
    pass


@rule(
    desc="Determine all Python interpreter versions used by Flake8 in your project",
    level=LogLevel.DEBUG,
)
async def setup_flake8_lockfile(
    _: Flake8LockfileSentinel, flake8: Flake8, python_setup: PythonSetup
) -> PythonLockfileRequest:
    all_build_targets = await Get(UnexpandedTargets, AddressSpecs([DescendantAddresses("")]))
    unique_constraints = {
        InterpreterConstraints.create_from_compatibility_fields(
            [tgt[InterpreterConstraintsField]], python_setup
        )
        for tgt in all_build_targets
        if tgt.has_field(InterpreterConstraintsField) and not tgt.get(SkipFlake8Field).value
    }
    constraints = InterpreterConstraints(itertools.chain.from_iterable(unique_constraints))
    return PythonLockfileRequest.from_tool(
        flake8, constraints or InterpreterConstraints(python_setup.interpreter_constraints)
    )


def rules():
    return (*collect_rules(), UnionRule(PythonToolLockfileSentinel, Flake8LockfileSentinel))
