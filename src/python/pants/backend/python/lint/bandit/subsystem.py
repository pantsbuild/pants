# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.option.custom_types import file_option, shell_str


class Bandit(PythonToolBase):
    options_scope = "bandit"
    help = "A tool for finding security issues in Python code (https://bandit.readthedocs.io)."

    default_version = "bandit>=1.6.2,<1.7"
    # `setuptools<45` is for Python 2 support. `stevedore` is because the 3.0 release breaks Bandit.
    default_extra_requirements = ["setuptools<45", "stevedore<3"]
    default_main = ConsoleScript("bandit")

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
