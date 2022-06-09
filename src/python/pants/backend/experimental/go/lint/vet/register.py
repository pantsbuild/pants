# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.experimental.go.register import rules as go_rules
from pants.backend.go.lint.vet import skip_field
from pants.backend.go.lint.vet.rules import rules as go_vet_rules


def rules():
    return [
        *go_vet_rules(),
        *skip_field.rules(),
        *go_rules(),
    ]
