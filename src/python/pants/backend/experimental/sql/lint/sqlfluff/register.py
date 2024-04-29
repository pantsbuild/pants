# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.sql.lint.sqlfluff import rules as sqlfluff_rules
from pants.backend.sql.lint.sqlfluff import skip_field, subsystem


def rules():
    return [
        *subsystem.rules(),
        *sqlfluff_rules.rules(),
        *skip_field.rules(),
    ]
