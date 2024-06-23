# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.experimental.scala.register import rules as all_scala_rules
from pants.backend.scala.lint.scalafix import extra_fields
from pants.backend.scala.lint.scalafix import rules as scalafix_rules


def rules():
    return [
        *all_scala_rules(),
        *scalafix_rules.rules(),
        *extra_fields.rules(),
    ]
