# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple, cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.option.custom_types import shell_str


class Autoflake(PythonToolBase):
    options_scope = "autoflake"
    help = (
        "The Python tool for removing unused/useless statements (imports, variables, duplicate keys, pass-es) "
        "etc. (https://github.com/myint/autoflake)."
    )

    default_version = "autoflake>=1.3,<=1.4"
    default_main = ConsoleScript("autoflake")
    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython==2.7.*", "CPython>=3.4,<3.9"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=f"Don't use autoflake when running `{register.bootstrap.pants_bin_name} lint`",
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=(
                "Arguments to pass directly to autoflake, e.g. "
                f'`--{cls.options_scope}-args="--remove-unused-variables --remove-duplicate-keys"`.'
            ),
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> Tuple[str, ...]:
        return tuple(self.options.args)
