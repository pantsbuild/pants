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
    default_version = "2.28.0"
    default_known_versions = [
        # checksums from https://github.com/goreleaser/nfpm/releases/download/v2.28.0/checksums.txt
        "2.28.0|linux_arm64 |0754838455f61adfff821be0404965f6844d42e883f227c6c973f404d422e890|4594814",
        "2.28.0|linux_x86_64|c948faaed97ca16ac2a4e24c42119606130ee0b371011a203d7a1c34ff422ea0|5050638",
        "2.28.0|macos_arm64 |9fdfd9871df2877388bbd71e505ee9524470d7fd23d7074ea8cc7ea0b42b88b7|4986427",
        "2.28.0|macos_x86_64|3bcc807a05ba3a0dbf62409064cd165256b9dcae2d317aa44b6c321142818a3e|5251388",
        # "2.28.0|win_arm64 |76cacd133c5d1ac9adafc8a85d5e40605287fe0dadee00c0cca106bab52a8951|4717144",
        # "2.28.0|win_x86_64|30de182bf1b7348b2c7fbf0554d0aa95aa569ee1bea81dc3e848af4217b7175e|5189195",
    ]

    default_url_template = (
        "https://github.com/goreleaser/nfpm/releases/download/v{version}/nfpm_{version}_{platform}.tar.gz"
        # Windows uses .zip instead of .tar.gz
    )

    default_url_platform_mapping = {
        "macos_arm64": "Darwin_arm64",
        "macos_x86_64": "Darwin_x86_64",
        "linux_arm64": "Linux_arm64",
        "linux_x86_64": "Linux_x86_64",
        # "win_arm64": "Windows_arm64",
        # "win_x86_64": "Windows_x86_64",
    }

    # all args controlled via target options
    # config file generated based on target options

    def generate_exe(self, plat: Platform) -> str:
        return "./nfpm"
