# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import BoolOption, SkipOption
from pants.util.strutil import softwrap


class GoogleJavaFormatSubsystem(JvmToolBase):
    options_scope = "google-java-format"
    name = "Google Java Format"
    help = "Google Java Format (https://github.com/google/google-java-format)"

    default_version = "1.13.0"
    default_artifacts = ("com.google.googlejavaformat:google-java-format:{version}",)
    default_lockfile_resource = (
        "pants.backend.java.lint.google_java_format",
        "google_java_format.default.lockfile.txt",
    )

    skip = SkipOption("fmt", "lint")
    aosp = BoolOption(
        default=False,
        help=softwrap(
            """
            Use AOSP style instead of Google Style (4-space indentation).
            ("AOSP" is the Android Open Source Project.)
            """
        ),
    )
