# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.core.util_rules import external_tool
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform

logger = logging.getLogger(__name__)


class NfpmSubsystem(TemplatedExternalTool):
    name = "nFPM"
    options_scope = "nfpm"
    help = "The nFPM deb, rpm, apk, and archlinux packager (https://nfpm.goreleaser.com)."

    # The version WITHOUT the 'v' prefix which we add as needed in the url_template.
    default_version = "2.38.0"  # released 05 July 2024
    # v2.35.0 added SOURCE_DATE_EPOCH support
    # v2.36.0 added rpm.scripts.verify
    # v2.37.0 added support for IPK packaging (TODO: add IPK package target+fields+rules)
    default_known_versions = [
        # checksums from https://github.com/goreleaser/nfpm/releases/download/v2.38.0/checksums.txt
        "2.38.0|linux_arm64 |e63be8d586d7c8f6af06945956aa29fb88388caa19d7c5b652f41ae37a155b27|4780662",
        "2.38.0|linux_x86_64|d9eebe93ee2832cfc8435b3f79ee92a845f1e5fbb99db5a3777a0013e175170d|5196368",
        "2.38.0|macos_arm64 |48788831696cf056b1a0f9f52e187dbb65c191f5488962696ab3b98fff9f7821|4978997",
        "2.38.0|macos_x86_64|781420f18ed6bd84a437fe3b272c1b1a03bad546aaaf4f7251b21c25a24ce32b|5294310",
        "2.38.0|win_arm64   |1a9c7fcd50eb105231f6f6f6cb90d7cdf50e6c34665eb6e881a185387ad158b1|4888861",
        "2.38.0|win_x86_64  |3124f9bb838410ef98eebfed2267670790ce6bb262ae2a6ca1938a69e087593b|5389117",
    ]

    default_url_template = (
        "https://github.com/goreleaser/nfpm/releases/download/v{version}/nfpm_{version}_{platform}"
    )

    default_url_platform_mapping = {
        # Platform includes the extension because Windows uses .zip instead of .tar.gz
        "macos_arm64": "Darwin_arm64.tar.gz",
        "macos_x86_64": "Darwin_x86_64.tar.gz",
        "linux_arm64": "Linux_arm64.tar.gz",
        "linux_x86_64": "Linux_x86_64.tar.gz",
        "win_arm64": "Windows_arm64.zip",
        "win_x86_64": "Windows_x86_64.zip",
    }

    # all args controlled via target options
    # config file generated based on target options

    def generate_exe(self, plat: Platform) -> str:
        return "./nfpm"


def rules():
    return external_tool.rules()
