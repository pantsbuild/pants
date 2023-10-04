# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import SkipOption


class ScalafmtSubsystem(JvmToolBase):
    options_scope = "scalafmt"
    name = "scalafmt"
    help = "scalafmt (https://scalameta.org/scalafmt/)"

    default_version = "3.2.1"
    default_artifacts = ("org.scalameta:scalafmt-cli_2.13:{version}",)
    default_lockfile_resource = (
        "pants.backend.scala.lint.scalafmt",
        "scalafmt.default.lockfile.txt",
    )

    skip = SkipOption("fmt", "lint")
