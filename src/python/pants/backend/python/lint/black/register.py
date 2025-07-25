# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Autoformatter for Python.

See https://www.pantsbuild.org/docs/python-linters-and-formatters and
https://black.readthedocs.io/en/stable/.
"""

from pants.backend.python.lint.black import rules as black_rules
from pants.backend.python.lint.black import skip_field, subsystem


def rules():
    return (*black_rules.rules(), *skip_field.rules(), *subsystem.rules())
