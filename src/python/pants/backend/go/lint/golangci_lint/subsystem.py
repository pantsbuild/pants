# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption
from pants.util.strutil import softwrap


class GolangciLint(TemplatedExternalTool):
    options_scope = "golangci-lint"
    name = "golangci-lint"
    help = "A fast Go linters runner"

    default_version = "1.51.1"
    default_known_versions = [
        "1.51.1|macos_arm64 |75b8f0ff3a4e68147156be4161a49d4576f1be37a0b506473f8c482140c1e7f2|9724049",  # noqa: E501
        "1.51.1|macos_x86_64|fba08acc4027f69f07cef48fbff70b8a7ecdfaa1c2aba9ad3fb31d60d9f5d4bc|10054954",  # noqa: E501
        "1.51.1|linux_arm64 |9744bc34e7b8d82ca788b667bfb7155a39b4be9aef43bf9f10318b1372cea338|8927955",  # noqa: E501
        "1.51.1|linux_x86_64|17aeb26c76820c22efa0e1838b0ab93e90cfedef43fbfc9a2f33f27eb9e5e070|9712769",  # noqa: E501
    ]
    default_url_template = (
        "https://github.com/golangci/golangci-lint/releases/download/v{version}/"
        "golangci-lint-{version}-{platform}.tar.gz"
    )
    default_url_platform_mapping = {
        "macos_arm64": "darwin-arm64",
        "macos_x86_64": "darwin-amd64",
        "linux_arm64": "linux-arm64",
        "linux_x86_64": "linux-amd64",
    }

    skip = SkipOption("lint")
    args = ArgsListOption(example="--enable gocritic")
    config = FileOption(
        "--config",
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to a YAML config file understood by golangci-lint
            (https://golangci-lint.run/usage/configuration/#config-file).

            Setting this option will disable `[{cls.options_scope}].config_discovery`.
            Use this option if the config is located in a non-standard location.
            """
        ),
    )
    config_discovery = BoolOption(
        "--config-discovery",
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include all relevant config files during runs
            (`.golangci.yml`, `.golangci.yaml`, `golangci.toml`, and `golangci.json`).

            Use `[{cls.options_scope}].config` instead if your config is in a
            non-standard location.
            """
        ),
    )

    def config_request(self) -> ConfigFilesRequest:
        # Refer to https://golangci-lint.run/usage/configuration
        # for how config files are discovered.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=[
                ".golangci.json",
                ".golangci.toml",
                ".golangci.yaml",
                ".golangci.yml",
            ],
        )

    def generate_exe(self, platform: Platform) -> str:
        return (
            f"./golangci-lint-{self.version}-"
            f"{self.url_platform_mapping[platform.value]}/golangci-lint"
        )
