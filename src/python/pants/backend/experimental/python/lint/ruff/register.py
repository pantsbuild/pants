# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Linter & formatter for Python.

See https://www.pantsbuild.org/docs/python-linters-and-formatters and https://docs.astral.sh/ruff/
"""

from pants.backend.python.lint.ruff import rules as ruff_rules
from pants.backend.python.lint.ruff import skip_field, subsystem
from pants.base.deprecated import warn_or_error


def rules():
    warn_or_error(
        "2.23.0.dev0",
        "Using the experimental Ruff backend",
        "The ruff backend has moved to `pants.backend.python.lint.ruff`",
        start_version="2.20.0",
    )
    return (*ruff_rules.rules(), *skip_field.rules(), *subsystem.rules())
