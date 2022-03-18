# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.option.option_types import ArgsListOption


class PyOxidizer(PythonToolBase):
    options_scope = "pyoxidizer"
    name = "PyOxidizer"
    help = (
        "The PyOxidizer utility for packaging Python code in a Rust binary "
        "(https://pyoxidizer.readthedocs.io/en/stable/pyoxidizer.html).\n\n"
        "Used with the `pyoxidizer_binary` target."
    )

    default_version = "pyoxidizer==0.18.0"
    default_main = ConsoleScript("pyoxidizer")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.8,<4"]

    args = ArgsListOption(example="--release")
