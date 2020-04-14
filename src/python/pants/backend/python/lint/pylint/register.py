# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Linter for Python.

See https://www.pylint.org.
"""

from pants.backend.python.lint.pylint import rules as pylint_rules


def rules():
    return pylint_rules.rules()
