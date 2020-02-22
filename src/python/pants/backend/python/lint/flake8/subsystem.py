# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import file_option, shell_str


class Flake8(PythonToolBase):
    options_scope = "flake8"
    default_version = "flake8>=3.7.9,<3.8"
    # `setuptools<45` is for Python 2 support.
    # TODO: Remove `enum34==1.1.6` once this enum34 regression is fixed:
    #  https://bitbucket.org/stoneleaf/enum34/issues/27/enum34-118-broken
    default_extra_requirements = ["setuptools<45", "enum34==1.1.6"]
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
