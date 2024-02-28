# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Linter & formatter for Python.

See https://www.pantsbuild.org/docs/python-linters-and-formatters and https://docs.astral.sh/ruff/
"""

from pants.backend.python.lint.ruff import skip_field, subsystem
from pants.backend.python.lint.ruff.check import rules as ruff_rules
from pants.backend.python.lint.ruff.check import skip_field as ruff_check_skip_field


def rules():
    return (
        *ruff_rules.rules(),
        *skip_field.rules(),
        *ruff_check_skip_field.rules(),
        *subsystem.rules(),
    )
