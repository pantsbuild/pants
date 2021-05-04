# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.go.lint import fmt
from pants.backend.go.lint.gofmt import skip_field
from pants.backend.go.lint.gofmt.rules import rules as gofmt_rules


def rules():
    return [*fmt.rules(), *gofmt_rules(), *skip_field.rules()]
