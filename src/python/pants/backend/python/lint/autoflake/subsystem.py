# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.backend.python.goals.lockfile import PythonLockfileRequest, PythonToolLockfileSentinel
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.custom_types import shell_str
from pants.util.docutil import git_url


class Autoflake(PythonToolBase):
    options_scope = "autoflake"
    help = "The Autoflake Python code formatter (https://github.com/myint/autoflake)."

    default_version = "autoflake==1.4"
    default_main = ConsoleScript("autoflake")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.autoflake", "lockfile.txt")
    default_lockfile_path = "src/python/pants/backend/python/lint/autoflake/lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=(
                f"Don't use Autoflake when running `{register.bootstrap.pants_bin_name} fmt` and "
                f"`{register.bootstrap.pants_bin_name} lint`"
            ),
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=(
                "Arguments to pass directly to Autoflake, e.g. "
                f'`--{cls.options_scope}-args="--target-version=py37 --quiet"`'
            ),
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> tuple[str, ...]:
        return tuple(self.options.args)


class AutoflakeLockfileSentinel(PythonToolLockfileSentinel):
    options_scope = Autoflake.options_scope


@rule()
async def setup_autoflake_lockfile(
    _: AutoflakeLockfileSentinel, autoflake: Autoflake
) -> PythonLockfileRequest:
    return PythonLockfileRequest.from_tool(autoflake)


def rules():
    return (*collect_rules(), UnionRule(PythonToolLockfileSentinel, AutoflakeLockfileSentinel))
