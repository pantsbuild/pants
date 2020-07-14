# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Optional, Tuple, cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import file_option, shell_str


class MyPy(PythonToolBase):
    """The MyPy Python type checker (http://mypy-lang.org/)."""

    options_scope = "mypy"
    default_version = "mypy==0.781"
    default_entry_point = "mypy"
    default_interpreter_constraints = ["CPython>=3.5"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip", type=bool, default=False, help="Don't use MyPy when running `./pants lint`."
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help="Arguments to pass directly to mypy, e.g. "
            '`--mypy-args="--python-version 3.7 --disallow-any-expr"`',
        )
        register(
            "--config",
            type=file_option,
            advanced=True,
            help="Path to `mypy.ini` or alternative MyPy config file",
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
