# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.lint.buf import skip_field
from pants.backend.codegen.protobuf.lint.buf.format_rules import rules as buf_format_rules
from pants.backend.codegen.protobuf.lint.buf.lint_rules import rules as buf_lint_rules


def rules():
    return (*buf_format_rules(), *buf_lint_rules(), *skip_field.rules())
