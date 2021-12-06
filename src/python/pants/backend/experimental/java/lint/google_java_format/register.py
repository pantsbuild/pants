# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.java.lint.google_java_format import rules as fmt_rules
from pants.backend.java.lint.google_java_format import skip_field


def rules():
    return [
        *fmt_rules.rules(),
        *skip_field.rules(),
    ]
