# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Downloads the trufflehog binary."""

from __future__ import annotations

from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import ExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import ArgsListOption, BoolOption, SkipOption, StrListOption
from pants.util.strutil import softwrap


class Trufflehog(ExternalTool):
    """A tool for finding secrets in code."""

    options_scope = "trufflehog"
    name = "Trufflehog"
    default_version = "v3.34.0"
    help = "Trufflehog secrets scanning"
    skip = SkipOption("lint")
    default_known_versions = [
        "v3.34.0|macos_arm64|19e10e34e95d797cbb924b342b873caa9e71296f9bead28b390d96981f47fbb0|26743363",
        "v3.34.0|macos_x86_64|6a0a425be18ef1b3c0bf5ff88a895e01c1de70892ee48026b9a9ed89ad0398d4|27466237",
        "v3.34.0|linux_arm64|6aeb5a91dbd981a5446312946072b470dc3a706711c85966394f62717cd71111|26021125",
        "v3.34.0|linux_x86_64|2fda581fb26ed5c866045a4532ce73511f873b70f20eaaae01a7279c3b1c2993|27805118",
    ]

    exclude = StrListOption(
        default=["README.md"],
        help=softwrap(
            """
            Exclude paths matching these globs from trufflehog scans.
            """
        ),
    )

    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=softwrap(
            """
            If a trufflehog-config.yaml file is found, pass it to the trufflehog --config argument.
            """
        ),
    )

    args = ArgsListOption(
        example="--no-json --exclude-detectors detector",
        default=["--json"],
        extra_help="This includes --json by default to reduce the volume of output.",
    )

    def generate_url(self, plat: Platform) -> str:
        """Returns the download URL for the trufflehog binary, depending on the current
        environment."""
        plat_str = {
            "macos_arm64": "darwin_arm64",
            "macos_x86_64": "darwin_amd64",
            "linux_arm64": "linux_arm64",
            "linux_x86_64": "linux_amd64",
        }[plat.value]

        version = self.version.replace("v", "")
        return (
            f"https://github.com/trufflesecurity/trufflehog/releases/download/{self.version}/"
            f"trufflehog_{version}_{plat_str}.tar.gz"
        )

    def generate_exe(self, plat: Platform) -> str:
        return "./trufflehog"

    def config_request(self) -> ConfigFilesRequest:
        """Load the config file."""
        return ConfigFilesRequest(
            discovery=self.config_discovery,
            check_existence=["trufflehog-config.yaml"],
        )
