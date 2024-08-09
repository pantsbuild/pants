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
    default_version = "2.37.1"  # released 09 May 2024
    # v2.35.0 added SOURCE_DATE_EPOCH support
    # v2.36.0 added rpm.scripts.verify
    # v2.37.0 added support for IPK packaging (TODO: add IPK package target+fields+rules)
    default_known_versions = [
        # checksums from https://github.com/goreleaser/nfpm/releases/download/v2.37.1/checksums.txt
        "2.37.1|linux_arm64 |df8f272195b7ddb09af9575673a9b8111f9eb7529cdd0a3fac4d44b52513a1e1|4780446",
        "2.37.1|linux_x86_64|3e1fe85c9a224a221c64cf72fc19e7cd6a0a51a5c4f4b336e3b8eccd417116a3|5195594",
        "2.37.1|macos_arm64 |5162ce5a59fe8d3b511583cb604c34d08bd2bcced87d9159c7005fc35287b9cd|4976450",
        "2.37.1|macos_x86_64|0213fa5d5af6f209d953c963103f9b6aec8a0e89d4bf0ab3d531f5f8b20b8eeb|5293359",
        "2.37.1|win_arm64   |d6edb839381d29ee1eb5eaa1a9443cf8d90f16e686a80b2245d650ed61268573|4884573",
        "2.37.1|win_x86_64  |2cc80804188048a577dd940a7a7cf04e2c57304fdf339c8692e50b43d3bc3bd4|5386526",
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
