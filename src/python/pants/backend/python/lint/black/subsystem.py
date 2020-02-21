# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import file_option, shell_str


class Black(PythonToolBase):
    options_scope = "black"
    default_version = "black==19.10b0"
    default_extra_requirements = ["setuptools"]
    default_entry_point = "black:patched_main"
    default_interpreter_constraints = ["CPython>=3.6"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help="Don't use Black when running `./pants fmt` and `./pants lint`",
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help="Arguments to pass directly to Black, e.g. "
            '`--black-args="--target-version=py37 --quiet"`',
        )
        register(
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help="Path to Black's pyproject.toml config file",
        )
