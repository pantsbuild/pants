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

    default_version = "v2.10.0"
    default_known_versions = [
        "v2.10.0|macos_x86_64|59f0523069a857ae918b8ac0774230013f7bcc00c1ea28119c2311353120867a|2514960",
        # "v2.10.0|macos_arm64" is not available at https://github.com/hadolint/hadolint/releases/
        "v2.10.0|linux_x86_64|8ee6ff537341681f9e91bae2d5da451b15c575691e33980893732d866d3cefc4|2301804",
        "v2.10.0|linux_arm64 |b53d5ab10707a585c9e72375d51b7357522300b5329cfa3f91e482687176e128|27954520",
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
