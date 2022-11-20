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

    default_version = "1.50.1"
    default_known_versions = [
        "1.50.1|macos_arm64 |3ca9753d7804b34f9165427fbe339dbea69bd80be8a10e3f02c6037393b2e1c4|9726190",  # noqa: E501
        "1.50.1|macos_x86_64|0f615fb8c364f6e4a213f2ed2ff7aa1fc2b208addf29511e89c03534067bbf57|10007042",  # noqa: E501
        "1.50.1|linux_arm64 |3ea0a6d5946340f6831646e2c67a317dd9b35bdc4e09b2df953a86f09ba05d74|8911583",  # noqa: E501
        "1.50.1|linux_x86_64|4ba1dc9dbdf05b7bdc6f0e04bdfe6f63aa70576f51817be1b2540bbce017b69a|9682295",  # noqa: E501
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
