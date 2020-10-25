# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple, cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import file_option, shell_str


class Isort(PythonToolBase):
    """The Python import sorter tool (https://timothycrosley.github.io/isort/)."""

    options_scope = "isort"
    default_version = "isort[pyproject]>=5.5.1,<5.6"
    default_extra_requirements = ["setuptools"]
    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6"]
    default_entry_point = "isort.main"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=(
                f"Don't use isort when running `{register.bootstrap.pants_bin_name} fmt` and "
                f"`{register.bootstrap.pants_bin_name} lint`."
            ),
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=(
                "Arguments to pass directly to isort, e.g. "
                f'`--{cls.options_scope}-args="--case-sensitive --trailing-comma"`.'
            ),
        )
        register(
            "--config",
            type=list,
            member_type=file_option,
            advanced=True,
            help="Path to `isort.cfg` or alternative isort config file(s).",
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> Tuple[str, ...]:
        return tuple(self.options.args)

    @property
    def config(self) -> Tuple[str, ...]:
        return tuple(self.options.config)
