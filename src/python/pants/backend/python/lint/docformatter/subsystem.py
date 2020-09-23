# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple, cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import shell_str


class Docformatter(PythonToolBase):
    """The Python docformatter tool (https://github.com/myint/docformatter)."""

    options_scope = "docformatter"
    default_version = "docformatter>=1.3.1,<1.4"
    default_entry_point = "docformatter:main"
    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython==2.7.*", "CPython>=3.4,<3.9"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=(
                f"Don't use docformatter when running `{register.bootstrap.pants_bin_name} fmt` "
                f"and `{register.bootstrap.pants_bin_name} lint`."
            ),
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=(
                "Arguments to pass directly to docformatter, e.g. "
                f'`--{cls.options_scope}-args="--wrap-summaries=100 --pre-summary-newline"`.'
            ),
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> Tuple[str, ...]:
        return tuple(self.options.args)
