from pants.backend.sql.lint.sqlfluff import rules as sqlfluff_rules
from pants.backend.sql.lint.sqlfluff import skip_field, subsystem


def rules():
    return [
        *subsystem.rules(),
        *sqlfluff_rules.rules(),
        *skip_field.rules(),
    ]
