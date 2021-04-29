# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript


class Lambdex(PythonToolBase):
    options_scope = "lambdex"
    help = "A tool for turning .pex files into AWS Lambdas (https://github.com/wickman/lambdex)."

    default_version = "lambdex==0.1.4"
    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6"]
    default_main = ConsoleScript("lambdex")
