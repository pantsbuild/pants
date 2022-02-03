# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.engine.rules import collect_rules
from pants.option.custom_types import shell_str


class PyOxidizer(PythonToolBase):
    options_scope = "pyoxidizer"
    help = """The PyOxidizer utility for packaging Python code in a Rust binary (https://pyoxidizer.readthedocs.io/en/stable/pyoxidizer.html)."""

    default_version = "pyoxidizer==0.18.0"
    default_main = ConsoleScript("pyoxidizer")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.8"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=(
                "Arguments to pass directly to PyOxidizer, e.g. "
                f'`--{cls.options_scope}-args="--release"`'
            ),
        )

    @property
    def args(self) -> Tuple[str, ...]:
        return tuple(self.options.args)


def rules():
    return (*collect_rules(),)
