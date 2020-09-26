# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Optional, Tuple, cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import file_option, shell_str


class Bandit(PythonToolBase):
    """A tool for finding security issues in Python code (https://bandit.readthedocs.io)."""

    options_scope = "bandit"
    default_version = "bandit>=1.6.2,<1.7"
    # `setuptools<45` is for Python 2 support. `stevedore` is because the 3.0 release breaks Bandit.
    default_extra_requirements = ["setuptools<45", "stevedore<3"]
    default_entry_point = "bandit"

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
            help="Path to a Bandit YAML config file",
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> Tuple[str, ...]:
        return tuple(self.options.args)

    @property
    def config(self) -> Optional[str]:
        return cast(Optional[str], self.options.config)
