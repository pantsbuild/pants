# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.backend.python.goals.lockfile import PythonLockfileRequest, PythonToolLockfileSentinel
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.custom_types import file_option, shell_str
from pants.util.docutil import git_url


class Twine(PythonToolBase):
    options_scope = "twine"
    help = "The utility for publishing Python distributions to PyPi and other Python repositories."

    default_version = "twine==3.6.0"
    default_main = ConsoleScript("twine")

    # This explicit dependency resolves a weird behavior in poetry, where it would include a sys
    # platform constraint on "Windows" when this was included transitively from the twine
    # requirements.
    # See: https://github.com/pantsbuild/pants/pull/13594#issuecomment-968154931
    default_extra_requirements = ["colorama>=0.4.3"]

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.subsystems", "twine_lockfile.txt")
    default_lockfile_path = "src/python/pants/backend/python/subsystems/twine_lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help="Don't use Twine when running `./pants publish`.",
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=("Arguments to pass directly to Twine, e.g. `--twine-args='--skip-existing'`.'"),
        )
        register(
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help=(
                "Path to a .pypirc config file to use. "
                "(https://packaging.python.org/specifications/pypirc/)\n\n"
                f"Setting this option will disable `[{cls.options_scope}].config_discovery`. Use "
                "this option if the config is located in a non-standard location."
            ),
        )
        register(
            "--config-discovery",
            type=bool,
            default=True,
            advanced=True,
            help=(
                "If true, Pants will include all relevant config files during runs "
                "(`.pypirc`).\n\n"
                f"Use `[{cls.options_scope}].config` instead if your config is in a "
                "non-standard location."
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

    def config_request(self) -> ConfigFilesRequest:
        # Refer to https://twine.readthedocs.io/en/latest/#configuration for how config files are
        # discovered.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=cast(bool, self.options.config_discovery),
            check_existence=[".pypirc"],
        )


class TwineLockfileSentinel(PythonToolLockfileSentinel):
    options_scope = Twine.options_scope


@rule
def setup_twine_lockfile(_: TwineLockfileSentinel, twine: Twine) -> PythonLockfileRequest:
    return PythonLockfileRequest.from_tool(twine)


def rules():
    return (*collect_rules(), UnionRule(PythonToolLockfileSentinel, TwineLockfileSentinel))
