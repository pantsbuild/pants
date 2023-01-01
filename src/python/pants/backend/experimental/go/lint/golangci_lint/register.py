# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.experimental.go.register import rules as go_rules
from pants.backend.go.lint.golangci_lint import skip_field
from pants.backend.go.lint.golangci_lint.rules import rules as golangci_lint_rules


def rules():
    return [
        *golangci_lint_rules(),
        *skip_field.rules(),
        *go_rules(),
    ]
