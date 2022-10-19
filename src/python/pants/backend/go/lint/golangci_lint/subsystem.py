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

    default_version = "1.49.0"
    default_known_versions = [
        "1.49.0|macos_arm64 |cabb1a4c35fe1dadbe5a81550a00871281a331e7660cd85ae16e936a7f0f6cfc|9633841",  # noqa: E501
        "1.49.0|macos_x86_64|20cd1215e0420db8cfa94a6cd3c9d325f7b39c07f2415a02d111568d8bc9e271|9916129",  # noqa: E501
        "1.49.0|linux_arm64 |b57ed03d29b8ca69be9925edd67ea305b6013cd5c97507d205fbe2979f71f2b5|8826411",  # noqa: E501
        "1.49.0|linux_x86_64|5badc6e9fee2003621efa07e385910d9a88c89b38f6c35aded153193c5125178|9590505",  # noqa: E501
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
