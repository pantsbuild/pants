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

    default_version = "7.1.2"
    default_known_versions = [
        "7.1.2|macos_x86_64|687c49c318fb655970cf716eed3c7bfc9caeea4f2931a2fd36593c458de0c537|7591232",
        "7.1.2|macos_arm64 |d0909b645496608fd6dfc67f95d9d3b01d90736d7b8c8ec41e802cb0b7ceae7c|7528994",
        "7.1.2|linux_x86_64|28285fe7e39ed23dc1a3a525dfcdccbc96c0034ff1d4277905d2672a71b38f13|7702060",
        "7.1.2|linux_arm64 |c22a44eee37b8927167ee6ee67573303f4e31171e7ec3a8ea021a6a660040437|7568336",
    ]
    default_url_template = "https://github.com/bazelbuild/buildtools/releases/download/v{version}/buildifier-{platform}"
    default_url_platform_mapping = {
        "macos_arm64": "darwin-arm64",
        "macos_x86_64": "darwin-amd64",
        "linux_arm64": "linux-arm64",
        "linux_x86_64": "linux-amd64",
    }

    skip = SkipOption("fmt")
    args = ArgsListOption(example="-lint=fix")

    # NB: buildifier doesn't (yet) support config files https://github.com/bazelbuild/buildtools/issues/479
