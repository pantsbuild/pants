# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Linter for Python.

Works with all Flake8 plugins. See https://flake8.pycqa.org/en/latest/.
"""

from pants.backend.python.lint.flake8 import rules as flake8_rules


def rules():
    return flake8_rules.rules()
