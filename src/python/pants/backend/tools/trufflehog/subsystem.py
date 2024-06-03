# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Downloads the trufflehog binary."""

from __future__ import annotations

from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import ExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import BoolOption, SkipOption, StrListOption
from pants.util.strutil import softwrap


class Trufflehog(ExternalTool):
    """A tool for finding secrets in code."""

    options_scope = "trufflehog"
    name = "Trufflehog"
    default_version = "v3.34.0"
    help = "Trufflehog secrets scanning"
    skip = SkipOption("lint")
    macos_arm_sha = "19e10e34e95d797cbb924b342b873caa9e71296f9bead28b390d96981f47fbb0"
    macos_amd_sha = "6a0a425be18ef1b3c0bf5ff88a895e01c1de70892ee48026b9a9ed89ad0398d4"
    linux_arm_sha = "6aeb5a91dbd981a5446312946072b470dc3a706711c85966394f62717cd71111"
    linux_amd_sha = "2fda581fb26ed5c866045a4532ce73511f873b70f20eaaae01a7279c3b1c2993"
    default_known_versions = [
        f"{default_version}|macos_arm64|{macos_arm_sha}|26743363",
        f"{default_version}|macos_x86_64|{macos_amd_sha}|27466237",
        f"{default_version}|linux_arm64|{linux_arm_sha}|26021125",
        f"{default_version}|linux_x86_64|{linux_amd_sha}|27805118",
    ]

    exclude_options = StrListOption(
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
