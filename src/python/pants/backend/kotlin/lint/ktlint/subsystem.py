# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import SkipOption
from pants.util.docutil import git_url


class KtlintSubsystem(JvmToolBase):
    options_scope = "ktlint"
    name = "Ktlint"
    help = "Ktlint, the anti-bikeshedding Kotlin linter with built-in formatter (https://ktlint.github.io/)"

    default_version = "0.45.2"
    default_artifacts = ("com.pinterest:ktlint:{version}",)
    default_lockfile_resource = (
        "pants.backend.kotlin.lint.ktlint",
        "ktlint.lock",
    )
    default_lockfile_path = "src/python/pants/backend/kotlin/lint/ktlint/ktlint.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    skip = SkipOption("fmt", "lint")
