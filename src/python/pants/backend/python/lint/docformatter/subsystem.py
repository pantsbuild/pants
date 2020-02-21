# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import shell_str


class Docformatter(PythonToolBase):
    options_scope = "docformatter"
    default_version = "docformatter>=1.3.1,<1.4"
    default_entry_point = "docformatter:main"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help="Don't use docformatter when running `./pants fmt` and `./pants lint`.",
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help="Arguments to pass directly to docformatter, e.g. "
            '`--docformatter-args="--wrap-summaries=100 --pre-summary-newline"`.',
        )
