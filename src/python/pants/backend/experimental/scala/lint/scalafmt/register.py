# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.experimental.scala.register import rules as all_scala_rules
from pants.backend.scala.lint import scala_lang_fmt
from pants.backend.scala.lint.scalafmt import rules as scalafmt_rules
from pants.backend.scala.lint.scalafmt import skip_field


def rules():
    return [
        *all_scala_rules(),
        *scala_lang_fmt.rules(),
        *scalafmt_rules.rules(),
        *skip_field.rules(),
    ]
