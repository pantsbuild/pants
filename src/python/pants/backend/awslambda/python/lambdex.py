# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase


class Lambdex(PythonToolBase):
    """A tool for turning .pex files into AWS Lambdas (https://github.com/wickman/lambdex)."""

    options_scope = "lambdex"
    default_version = "lambdex==0.1.3"
    # TODO(John Sirois): Remove when we can upgrade to a version of lambdex with
    # https://github.com/wickman/lambdex/issues/6 fixed.
    default_extra_requirements = ["setuptools>=50.3.0,<50.4"]
    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.5"]
    default_entry_point = "lambdex.bin.lambdex"
