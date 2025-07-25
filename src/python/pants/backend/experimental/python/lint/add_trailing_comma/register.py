# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Autoformatter to automatically add trailing commas to calls and literals.

See https://github.com/asottile/add-trailing-comma for details.
"""

from pants.backend.python.lint.add_trailing_comma import rules as add_trailing_comma_rules
from pants.backend.python.lint.add_trailing_comma import skip_field, subsystem


def rules():
    return (*add_trailing_comma_rules.rules(), *skip_field.rules(), *subsystem.rules())
