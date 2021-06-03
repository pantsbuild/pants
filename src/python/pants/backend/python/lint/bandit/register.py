# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Security linter for Python.

See https://www.pantsbuild.org/docs/python-linters-and-formatters and
https://bandit.readthedocs.io/en/latest/.
"""

from pants.backend.python.lint.bandit import rules as bandit_rules
from pants.backend.python.lint.bandit import skip_field


def rules():
    return (*bandit_rules.rules(), *skip_field.rules())
