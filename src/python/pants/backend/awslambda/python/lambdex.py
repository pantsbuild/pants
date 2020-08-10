# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase


class Lambdex(PythonToolBase):
    """A tool for turning .pex files into AWS Lambdas (https://github.com/wickman/lambdex)."""

    options_scope = "lambdex"
    default_version = "lambdex==0.1.3"
    default_entry_point = "lambdex.bin.lambdex"
