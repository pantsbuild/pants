# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Optional, Tuple, cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import file_option, shell_str


class Black(PythonToolBase):
    """The Black Python code formatter (https://black.readthedocs.io/)."""

    options_scope = "black"
    default_version = "black==20.8b1"
    default_extra_requirements = ["setuptools"]
    default_entry_point = "black:patched_main"
    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6"]

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
            help="Path to Black's pyproject.toml config file",
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
