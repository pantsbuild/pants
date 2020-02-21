# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import file_option, shell_str


class Bandit(PythonToolBase):
    options_scope = "bandit"
    default_version = "bandit>=1.6.2,<1.7"
    default_extra_requirements = ["setuptools<45"]  # `<45` is for Python 2 support
    default_entry_point = "bandit"
    default_interpreter_constraints = ["CPython>=2.7,<3", "CPython>=3.0"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip", type=bool, default=False, help="Don't use Bandit when running `./pants lint`"
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help="Arguments to pass directly to Bandit, e.g. "
            '`--bandit-args="--skip B101,B308 --confidence"`',
        )
        register(
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help="Path to a Bandit YAML config file",
        )
