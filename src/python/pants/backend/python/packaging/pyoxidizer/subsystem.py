# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.engine.rules import collect_rules
from pants.option.option_types import ArgsListOption
from pants.util.strutil import help_text


class PyOxidizer(PythonToolBase):
    options_scope = "pyoxidizer"
    name = "PyOxidizer"
    help_short = help_text(
        """
        The PyOxidizer utility for packaging Python code in a Rust binary
        (https://pyoxidizer.readthedocs.io/en/stable/pyoxidizer.html).

        Used with the `pyoxidizer_binary` target.
        """
    )

    default_main = ConsoleScript("pyoxidizer")
    default_requirements = ["pyoxidizer>=0.18.0,<1"]

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.8,<4"]

    default_lockfile_resource = ("pants.backend.python.packaging.pyoxidizer", "pyoxidizer.lock")

    args = ArgsListOption(example="--release")


def rules():
    return collect_rules()
