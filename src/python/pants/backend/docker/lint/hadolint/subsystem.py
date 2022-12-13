# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption
from pants.util.strutil import softwrap


class Hadolint(TemplatedExternalTool):
    options_scope = "hadolint"
    name = "Hadolint"
    help = "A linter for Dockerfiles."

    default_version = "v2.12.0"
    default_known_versions = [
        "v2.12.0|macos_x86_64|2a5b7afcab91645c39a7cebefcd835b865f7488e69be24567f433dfc3d41cd27|2682896",
        "v2.12.0|macos_arm64 |2a5b7afcab91645c39a7cebefcd835b865f7488e69be24567f433dfc3d41cd27|2682896",  # same as mac x86
        "v2.12.0|linux_x86_64|56de6d5e5ec427e17b74fa48d51271c7fc0d61244bf5c90e828aab8362d55010|2426420",
        "v2.12.0|linux_arm64 |5798551bf19f33951881f15eb238f90aef023f11e7ec7e9f4c37961cb87c5df6|24002600",
    ]
    default_url_template = (
        "https://github.com/hadolint/hadolint/releases/download/{version}/hadolint-{platform}"
    )
    default_url_platform_mapping = {
        "macos_arm64": "Darwin-x86_64",
        "macos_x86_64": "Darwin-x86_64",
        "linux_arm64": "Linux-arm64",
        "linux_x86_64": "Linux-x86_64",
    }

    skip = SkipOption("lint")
    args = ArgsListOption(example="--format json")
    config = FileOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to an YAML config file understood by Hadolint
            (https://github.com/hadolint/hadolint#configure).

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
            If true, Pants will include all relevant config files during runs
            (`.hadolint.yaml` and `.hadolint.yml`).

            Use `[{cls.options_scope}].config` instead if your config is in a
            non-standard location.
            """
        ),
    )

    def config_request(self) -> ConfigFilesRequest:
        # Refer to https://github.com/hadolint/hadolint#configure for how config files are
        # discovered.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=[".hadolint.yaml", ".hadolint.yml"],
        )
