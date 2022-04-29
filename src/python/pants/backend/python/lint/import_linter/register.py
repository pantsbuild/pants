# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Linter for Python.

See https://import-linter.readthedocs.io/en/stable/index.html.
"""

from pants.backend.python.lint.import_linter import rules as import_linter_rules
from pants.backend.python.lint.import_linter import skip_field, subsystem


def rules():
    return (*import_linter_rules.rules(), *skip_field.rules(), *subsystem.rules())
