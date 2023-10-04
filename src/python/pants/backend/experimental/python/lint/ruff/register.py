# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Linter & formatter for Python.

See https://www.pantsbuild.org/docs/python-linters-and-formatters and https://github.com/charliermarsh/ruff
"""

from pants.backend.python.lint.ruff import rules as ruff_rules
from pants.backend.python.lint.ruff import skip_field, subsystem


def rules():
    return (*ruff_rules.rules(), *skip_field.rules(), *subsystem.rules())
