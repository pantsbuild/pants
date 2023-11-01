# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform

logger = logging.getLogger(__name__)


class NfpmSubsystem(TemplatedExternalTool):
    name = "nFPM"
    options_scope = "nfpm"
    help = "The nFPM deb, rpm, and apk packager (https://nfpm.goreleaser.com)."

    # The version WITHOUT the 'v' prefix which we add as needed in the url_template.
    default_version = "2.34.0"  # released 28 Oct 2023
    default_known_versions = [
        # checksums from https://github.com/goreleaser/nfpm/releases/download/v2.34.0/checksums.txt
        "2.34.0|linux_arm64 |9b4fe0e650bbbc9d27456290b2eeb0719472519593d98bf1a4ba152022a4e872|4659916",
        "2.34.0|linux_x86_64|1c97da72c055e3ddedf80bcfac155ccb008a99a55e59b3561c16ec4c6ce7e2c7|5067985",
        "2.34.0|macos_arm64 |75985dc7660b9de2462d2aa6027c40c2cb116248b9340f70a83e9441488369ab|5041781",
        "2.34.0|macos_x86_64|c5a7bd5fba2c9ba0b84a515439ecc5e61278c11643f99d577988bfe542f504be|5267411",
        "2.34.0|win_arm64   |9586a2a772b82c1c603df4f14de8434d48adcdba80ced2d83adda31f04ea1745|4757387",
        "2.34.0|win_x86_64  |72d1a774271bbfab3fa72b90fa5579c40a35d2536ca6782c86964064df9191d3|5252379",
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
