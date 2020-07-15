# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from typing import Optional

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import file_option, shell_str


class Flake8(PythonToolBase):
    """The Flake8 Python linter (https://flake8.pycqa.org/)."""

    options_scope = "flake8"
    default_version = "flake8>=3.7.9,<3.9"
    default_extra_requirements = ["setuptools<45"]  # NB: `<45` is for Python 2 support
    default_entry_point = "flake8"
    default_interpreter_constraints = ["CPython>=2.7,<3", "CPython>=3.4"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip", type=bool, default=False, help="Don't use Flake8 when running `./pants lint`"
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help="Arguments to pass directly to Flake8, e.g. "
            '`--flake8-args="--ignore E123,W456 --enable-extensions H111"`',
        )
        register(
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help="Path to `.flake8` or alternative Flake8 config file",
        )
        register(
            "--output-file",
            type=str,
            metavar="filename",
            default=None,
            advanced=True,
            help="Redirect report to a file.",
        )

    @property
    def output_file_path(self) -> Optional[Path]:
        output_file = self.options.output_file
        return Path(output_file) if output_file else None
