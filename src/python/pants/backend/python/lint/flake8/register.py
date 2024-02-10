# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Linter for Python.

See https://www.pantsbuild.org/docs/python-linters-and-formatters and
https://flake8.pycqa.org/en/latest/.
"""

from pants.backend.python.lint.flake8 import rules as flake8_rules
from pants.backend.python.lint.flake8 import skip_field, subsystem


def rules():
    return (*flake8_rules.rules(), *skip_field.rules(), *subsystem.rules())
