# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import ArgsListOption, SkipOption


class BufSubsystem(TemplatedExternalTool):
    options_scope = "buf"
    name = "Buf"
    help = "A linter and formatter for Protocol Buffers (https://github.com/bufbuild/buf)."

    default_version = "v1.2.1"
    default_known_versions = [
        "v1.2.1|linux_arm64 |8c9df682691436bd9f58efa44928e6fcd68ec6dd346e35eddac271786f4c0ae3|13940426",
        "v1.2.1|linux_x86_64|eb227afeaf5f5c5a5f1d2aca92926d8c89be5b7a410e5afd6dd68f2ed0c00f22|15267079",
        "v1.2.1|macos_arm64 |6877c9b8f895ec4962faff551c541d9d14e12f49b899ed7e553f0dc74a69b1b8|15388080",
        "v1.2.1|macos_x86_64|652b407fd08e5e664244971f4a725763ef582f26778674490658ad2ce361fe95|15954329",
    ]
    default_url_template = (
        "https://github.com/bufbuild/buf/releases/download/{version}/buf-{platform}.tar.gz"
    )
    default_url_platform_mapping = {
        "macos_arm64": "Darwin-arm64",
        "macos_x86_64": "Darwin-x86_64",
        "linux_arm64": "Linux-aarch64",
        "linux_x86_64": "Linux-x86_64",
    }

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--error-format json")

    def generate_exe(self, plat: Platform) -> str:
        return "./buf/bin/buf"
