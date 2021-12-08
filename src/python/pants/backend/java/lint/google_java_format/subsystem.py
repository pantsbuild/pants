# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import cast

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.util.docutil import git_url


class GoogleJavaFormatSubsystem(JvmToolBase):
    options_scope = "google-java-format"
    help = "Google Java Format (https://github.com/google/google-java-format)"

    default_version = "1.13.0"
    default_artifacts = ("com.google.googlejavaformat:google-java-format:{version}",)
    default_lockfile_resource = (
        "pants.backend.java.lint.google_java_format",
        "google_java_format.default.lockfile.txt",
    )
    default_lockfile_url = git_url(
        "src/python/pants/backend/java/lint/google_java_format/google_java_format.default.lockfile.txt"
    )

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=(
                f"Don't use Google Java Format when running `{register.bootstrap.pants_bin_name} fmt` and "
                f"`{register.bootstrap.pants_bin_name} lint`"
            ),
        )
        register(
            "--aosp",
            type=bool,
            default=False,
            help=(
                "Use AOSP style instead of Google Style (4-space indentation). "
                '("AOSP" is the Android Open Source Project.)'
            ),
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def aosp(self) -> bool:
        return cast(bool, self.options.aosp)
