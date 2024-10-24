# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import SkipOption


class KtlintSubsystem(JvmToolBase):
    options_scope = "ktlint"
    name = "Ktlint"
    help = "Ktlint, the anti-bikeshedding Kotlin linter with built-in formatter (https://pinterest.github.io/ktlint/)"

    default_version = "1.3.1"
    default_artifacts = ("com.pinterest.ktlint:ktlint-cli:{version}",)
    default_lockfile_resource = (
        "pants.backend.kotlin.lint.ktlint",
        "ktlint.lock",
    )

    skip = SkipOption("fmt", "lint")
