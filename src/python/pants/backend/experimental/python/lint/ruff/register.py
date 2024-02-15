# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Linter & formatter for Python.

See https://www.pantsbuild.org/docs/python-linters-and-formatters and https://docs.astral.sh/ruff/
"""

from pants.backend.experimental.python.lint.ruff.check import register as ruff_check
from pants.base.deprecated import warn_or_error


def rules():
    warn_or_error(
        "2.23.0.dev0",
        "The `pants.backend.experimental.python.lint.ruff` backend",
        hint="Use `pants.backend.experimental.python.lint.ruff.check` instead.",
        start_version="2.20.0.dev7",
    )
    return ruff_check_rules.rules()
