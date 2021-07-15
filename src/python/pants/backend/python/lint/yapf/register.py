# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Autoformatter for Python.

See https://www.pantsbuild.org/docs/python-linters-and-formatters and
https://github.com/google/yapf .
"""

from pants.backend.python.lint import python_fmt
from pants.backend.python.lint.yapf import rules as yapf_rules
from pants.backend.python.lint.yapf import skip_field, subsystem


def rules():
    return (*yapf_rules.rules(), *python_fmt.rules(), *skip_field.rules(), *subsystem.rules())
