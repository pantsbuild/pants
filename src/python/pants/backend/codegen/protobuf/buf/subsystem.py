# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption
from pants.util.strutil import softwrap


class BufSubsystem(TemplatedExternalTool):
    options_scope = "buf"
    name = "Buf"
    help = "A linter and formatter for Protocol Buffers (https://github.com/bufbuild/buf)."

    default_version = "v1.69.0"
    default_known_versions = [
        "v1.69.0|linux_arm64 |28b258cb4ee7a1224a61e1dd91ae5935f1c86c23e8e67bcfa23c8b096b0ad478|33862042",
        "v1.69.0|linux_x86_64|2b1f9cfb5e17d50c10dea9202979ffd28ca7ff7a6f4e51e801a9463986690b03|37497898",
        "v1.69.0|macos_arm64 |246534674239f326dd1ad2642e57865dd56dc4e98c4857d13da6eca4d3a168ad|35754114",
        "v1.69.0|macos_x86_64|570458723a1e400d654e916cc54a98e78a9c23d72775afde9ef12abcdebd37a1|38439569",
    ]
    default_url_template = (
        "https://github.com/bufbuild/buf/releases/download/{version}/buf-{platform}.tar.gz"
    )
    default_url_platform_mapping = {
        "macos_arm64": "Darwin-arm64",
        "macos_x86_64": "Darwin-x86_64",
        "linux_arm64": "Linux-aarch64",
        "linux_x86_64": "Linux-x86_64",
    }

    format_skip = SkipOption("fmt", "lint")
    lint_skip = SkipOption("lint")
    format_args = ArgsListOption(example="--error-format json")
    lint_args = ArgsListOption(example="--error-format json")

    config = FileOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to a config file understood by Buf
            (https://docs.buf.build/configuration/overview).

            Setting this option will disable `[{cls.options_scope}].config_discovery`. Use
            this option if the config is located in a non-standard location.
            """
        ),
    )
    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include any relevant root config files during runs
            (`buf.yaml`). If the json format is preferred, the path to the `buf.json`
            file should be provided in the config option.

            Use `[{cls.options_scope}].config` instead if your config is in a non-standard location.
            """
        ),
    )

    @property
    def config_request(self) -> ConfigFilesRequest:
        # Refer to https://docs.buf.build/configuration/overview.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"{self.options_scope}.config",
            discovery=self.config_discovery,
            check_existence=("buf.yaml",),
            check_content={},
        )

    def generate_exe(self, plat: Platform) -> str:
        return "./buf/bin/buf"
