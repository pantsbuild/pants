# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Autoformatter for removing unused Python imports.

See https://github.com/myint/autoflake for details.
"""

from pants.backend.python.lint.autoflake import rules as autoflake_rules
from pants.backend.python.lint.autoflake import skip_field, subsystem


def rules():
    return (*autoflake_rules.rules(), *skip_field.rules(), *subsystem.rules())
