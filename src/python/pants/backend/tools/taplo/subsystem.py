# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pathlib import PurePosixPath

from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import ArgsListOption, BoolOption, SkipOption, StrListOption
from pants.util.strutil import softwrap


class Taplo(TemplatedExternalTool):
    help = "An autoformatter for TOML files (https://taplo.tamasfe.dev/)"

    options_scope = "taplo"
    name = "Taplo"
    default_version = "0.8.0"
    default_known_versions = [
        "0.8.0|macos_arm64|79c1691c3c46be981fa0cec930ec9a6d6c4ffd27272d37d1885514ce59bd8ccf|3661689",
        "0.8.0|macos_x86_64|a1917f1b9168cb4f7d579422dcdf9c733028d873963d8fa3a6f499e41719c502|3926263",
        "0.8.0|linux_arm64|a6a94482f125c21090593f94cad23df099c4924f5b9620cda4a8653527c097a1|3995383",
        "0.8.0|linux_x86_64|3703294fac37ca9a9f76308f9f98c3939ccb7588f8972acec68a48d7a10d8ee5|4123593",
    ]
    default_url_template = (
        "https://github.com/tamasfe/taplo/releases/download/{version}/taplo-{platform}.gz"
    )
    default_url_platform_mapping = {
        "macos_arm64": "darwin-aarch64",
        "macos_x86_64": "darwin-x86_64",
        "linux_arm64": "linux-aarch64",
        "linux_x86_64": "linux-x86_64",
    }

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--option=align_entries=false")
    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=softwrap(
            """
            If true, Pants will include a `taplo.toml` or `.taplo.toml` file found in
            the build root during a run.
            """
        ),
    )

    glob_pattern = StrListOption(
        help=softwrap(
            """
            A list of glob patterns of files to include/exclude in formatting relative
            to the build root. Leading exclamation points exclude an item from
            formatting.

            Example:

                ["**/*.toml", "**/pyproject.toml", "!pyproject.toml"]

            The default includes all files with a `.toml` extension recursively and excludes
            `.taplo.toml` or `taplo.toml` files in the build root.
            """
        ),
        advanced=True,
        default=["**/*.toml", "!.taplo.toml", "!taplo.toml"],
    )

    def generate_exe(self, plat: Platform) -> str:
        exe = super().generate_exe(plat)
        return PurePosixPath(exe).stem

    def config_request(self) -> ConfigFilesRequest:
        return ConfigFilesRequest(
            discovery=self.config_discovery,
            check_existence=[".taplo.toml", "taplo.toml"],
        )
