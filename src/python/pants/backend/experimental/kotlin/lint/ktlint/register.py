# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.experimental.kotlin.register import rules as all_kotlin_rules
from pants.backend.kotlin.lint.ktlint import rules as ktlint_rules
from pants.backend.kotlin.lint.ktlint import skip_field


def rules():
    return [
        *all_kotlin_rules(),
        *ktlint_rules.rules(),
        *skip_field.rules(),
    ]
