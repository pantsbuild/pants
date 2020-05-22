# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import file_option, shell_str, target_option


class Pylint(PythonToolBase):
    options_scope = "pylint"
    default_version = "pylint>=2.4.4,<2.5"
    default_entry_point = "pylint"
    default_interpreter_constraints = ["CPython>=3.5"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip", type=bool, default=False, help="Don't use Pylint when running `./pants lint`"
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help="Arguments to pass directly to Pylint, e.g. "
            '`--pylint-args="--ignore=foo.py,bar.py --disable=C0330,W0311"`',
        )
        register(
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help="Path to `pylintrc` or alternative Pylint config file",
        )
        register(
            "--source-plugins",
            type=list,
            member_type=target_option,
            advanced=True,
            help=(
                "An optional list of `pylint_source_plugin` target addresses. This allows you to "
                "load custom plugins defined in source code. Run the goal `target-types "
                "--details=pylint_source_plugin` for instructions, including how to load "
                "third-party plugins."
            ),
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> List[str]:
        return cast(List[str], self.options.args)

    @property
    def config(self) -> Optional[str]:
        return cast(Optional[str], self.options.config)

    @property
    def source_plugins(self) -> List[str]:
        return cast(List[str], self.options.source_plugins)
