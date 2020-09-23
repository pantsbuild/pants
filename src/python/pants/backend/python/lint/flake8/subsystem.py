# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Optional, Tuple, cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import file_option, shell_str


class Flake8(PythonToolBase):
    """The Flake8 Python linter (https://flake8.pycqa.org/)."""

    options_scope = "flake8"
    default_version = "flake8>=3.7.9,<3.9"
    default_extra_requirements = ["setuptools<45"]  # NB: `<45` is for Python 2 support
    default_entry_point = "flake8"

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
            help="Path to `.flake8` or alternative Flake8 config file",
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
