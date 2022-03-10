# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.lint.buf import skip_field
from pants.backend.codegen.protobuf.lint.buf.rules import rules as buf_rules


def rules():
    return (*buf_rules(), *skip_field.rules())
