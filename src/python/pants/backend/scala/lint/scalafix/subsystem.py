# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import SkipOption, StrOption


class ScalafixSubsystem(JvmToolBase):
    options_scope = "scalafix"
    name = "scalafix"
    help = "scalafix (https://scalacenter.github.io/scalafix/)"

    default_version = "0.9.31"
    default_artifacts = ("ch.epfl.scala:scalafix-cli_2.13.6:{version}",)
    default_lockfile_resource = (
        "pants.backend.scala.lint.scalafix",
        "scalafix.default.lockfile.txt",
    )

    config_file_name = StrOption(
        default=".scalafix.conf", help="Name to look for when locating scalafix config files."
    )

    skip = SkipOption("fix", "fmt", "lint")
