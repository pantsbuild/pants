# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.option.option_types import ArgsListOption, SkipOption
from pants.util.strutil import help_text


class Buildifier(TemplatedExternalTool):
    options_scope = "buildifier"
    name = "Buildifier"
    help = help_text(
        """
        Buildifier is a tool for formatting BUILD files with a standard convention.

        Pants supports running Buildifier on your Pants BUILD files for several reasons:
          - You might like the style that buildifier uses.
          - You might be incrementally adopting Pants from Bazel, and are already using buildifier.

        Please note that there are differences from Bazel's BUILD files (which are Starlark) and
        Pants' BUILD files (which are Python), so buildifier may issue a syntax error.
        In practice, these errors should be rare. See https://bazel.build/rules/language#differences_with_python.
        """
    )

    default_version = "5.1.0"
    default_known_versions = [
        "5.1.0|macos_x86_64|c9378d9f4293fc38ec54a08fbc74e7a9d28914dae6891334401e59f38f6e65dc|7125968",
        "5.1.0|macos_arm64 |745feb5ea96cb6ff39a76b2821c57591fd70b528325562486d47b5d08900e2e4|7334498",
        "5.1.0|linux_x86_64|52bf6b102cb4f88464e197caac06d69793fa2b05f5ad50a7e7bf6fbd656648a3|7226100",
        "5.1.0|linux_arm64 |917d599dbb040e63ae7a7e1adb710d2057811902fdc9e35cce925ebfd966eeb8|7171938",
    ]
    default_url_template = (
        "https://github.com/bazelbuild/buildtools/releases/download/{version}/buildifier-{platform}"
    )
    default_url_platform_mapping = {
        "macos_arm64": "darwin-arm64",
        "macos_x86_64": "darwin-amd64",
        "linux_arm64": "linux-arm64",
        "linux_x86_64": "linux-amd64",
    }

    skip = SkipOption("fmt")
    args = ArgsListOption(example="-lint=fix")

    # NB: buildifier doesn't (yet) support config files https://github.com/bazelbuild/buildtools/issues/479
