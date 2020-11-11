# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Linter for Python.

See https://www.pantsbuild.org/docs/python-linters-and-formatters and https://www.pylint.org.
"""

from pants.backend.python.lint.pylint import rules as pylint_rules
from pants.backend.python.lint.pylint.plugin_target_type import PylintSourcePlugin


def rules():
    return pylint_rules.rules()


def target_types():
    return [PylintSourcePlugin]
