# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import ArgsListOption, SkipOption


class BufSubsystem(TemplatedExternalTool):
    options_scope = "buf-lint"
    name = "Buf"
    help = "A linter for Protocol Buffers (https://github.com/bufbuild/buf)."

    default_version = "v1.0.0"
    default_known_versions = [
        "v1.0.0|linux_arm64 |c4b095268fe0fc8de2ad76c7b4677ccd75f25623d5b1f971082a6b7f43ff1eb0|13378006",
        "v1.0.0|linux_x86_64|5f0ff97576cde9e43ec86959046169f18ec5bcc08e31d82dcc948d057212f7bf|14511545",
        "v1.0.0|macos_arm64 |e922c277487d941c4b056cac6c1b4c6e5004e8f3dda65ae2d72d8b10da193297|15147463",
        "v1.0.0|macos_x86_64|8963e1ab7685aac59b8805cc7d752b06a572b1c747a6342a9e73b94ccdf89ddb|15187858",
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

    skip = SkipOption("lint")
    args = ArgsListOption(example="--error-format json")

    def generate_exe(self, plat: Platform) -> str:
        return "./buf/bin/buf"
