# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""https://github.com/asottile/pyupgrade.

A tool  to automatically upgrade syntax for newer versions of the language.
"""

from pants.backend.python.lint.pyupgrade import rules as pyupgrade_rules
from pants.backend.python.lint.pyupgrade import skip_field, subsystem


def rules():
    return (*pyupgrade_rules.rules(), *skip_field.rules(), *subsystem.rules())
