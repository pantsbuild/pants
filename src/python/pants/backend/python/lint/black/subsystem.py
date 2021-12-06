# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from typing import Iterable, cast

from pants.backend.python.goals.lockfile import PythonLockfileRequest, PythonToolLockfileSentinel
from pants.backend.python.lint.black.skip_field import SkipBlackField
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import ConsoleScript
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import AllTargets, AllTargetsRequest
from pants.engine.unions import UnionRule
from pants.option.custom_types import file_option, shell_str
from pants.util.docutil import git_url
from pants.util.logging import LogLevel


class Black(PythonToolBase):
    options_scope = "black"
    help = "The Black Python code formatter (https://black.readthedocs.io/)."

    default_version = "black==21.12b0"
    default_main = ConsoleScript("black")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6.2"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.lint.black", "lockfile.txt")
    default_lockfile_path = "src/python/pants/backend/python/lint/black/lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=(
                f"Don't use Black when running `{register.bootstrap.pants_bin_name} fmt` and "
                f"`{register.bootstrap.pants_bin_name} lint`"
            ),
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=(
                "Arguments to pass directly to Black, e.g. "
                f'`--{cls.options_scope}-args="--target-version=py37 --quiet"`'
            ),
        )
        register(
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help=(
                "Path to a TOML config file understood by Black "
                "(https://github.com/psf/black#configuration-format).\n\n"
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
                "If true, Pants will include any relevant pyproject.toml config files during runs."
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

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # Refer to https://black.readthedocs.io/en/stable/usage_and_configuration/the_basics.html#where-black-looks-for-the-file
        # for how Black discovers config.
        candidates = {os.path.join(d, "pyproject.toml"): b"[tool.black]" for d in ("", *dirs)}
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=cast(bool, self.options.config_discovery),
            check_content=candidates,
        )


class BlackLockfileSentinel(PythonToolLockfileSentinel):
    options_scope = Black.options_scope


@rule(
    desc="Determine if Black should use Python 3.8+ (for lockfile usage)",
    level=LogLevel.DEBUG,
)
async def setup_black_lockfile(
    _: BlackLockfileSentinel, black: Black, python_setup: PythonSetup
) -> PythonLockfileRequest:
    if not black.uses_lockfile:
        return PythonLockfileRequest.from_tool(black)

    constraints = black.interpreter_constraints
    if black.options.is_default("interpreter_constraints"):
        all_tgts = await Get(AllTargets, AllTargetsRequest())
        # TODO: fix to use `FieldSet.is_applicable()`.
        code_constraints = InterpreterConstraints.create_from_targets(
            (tgt for tgt in all_tgts if not tgt.get(SkipBlackField).value), python_setup
        )
        if code_constraints.requires_python38_or_newer(python_setup.interpreter_universe):
            constraints = code_constraints

    return PythonLockfileRequest.from_tool(black, constraints)


def rules():
    return (*collect_rules(), UnionRule(PythonToolLockfileSentinel, BlackLockfileSentinel))
