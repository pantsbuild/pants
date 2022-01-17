# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.shell.lint.shfmt import skip_field
from pants.backend.shell.lint.shfmt.rules import rules as shfmt_rules


def rules():
    return [*shfmt_rules(), *skip_field.rules()]
