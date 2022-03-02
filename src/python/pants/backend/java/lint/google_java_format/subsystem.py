# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import BoolOption
from pants.util.docutil import bin_name, git_url


class GoogleJavaFormatSubsystem(JvmToolBase):
    options_scope = "google-java-format"
    help = "Google Java Format (https://github.com/google/google-java-format)"

    default_version = "1.13.0"
    default_artifacts = ("com.google.googlejavaformat:google-java-format:{version}",)
    default_lockfile_resource = (
        "pants.backend.java.lint.google_java_format",
        "google_java_format.default.lockfile.txt",
    )
    default_lockfile_path = "src/python/pants/backend/java/lint/google_java_format/google_java_format.default.lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)

    skip = BoolOption(
        "--skip",
        default=False,
        help=f"Don't use Google Java Format when running `{bin_name()} fmt` and `{bin_name()} lint`",
    )
    aosp = BoolOption(
        "--aosp",
        default=False,
        help=(
            "Use AOSP style instead of Google Style (4-space indentation). "
            '("AOSP" is the Android Open Source Project.)'
        ),
    )
