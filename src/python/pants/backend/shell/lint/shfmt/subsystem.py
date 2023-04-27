# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from typing import Iterable

from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.option.option_types import ArgsListOption, BoolOption, SkipOption
from pants.util.strutil import softwrap


class Shfmt(TemplatedExternalTool):
    options_scope = "shfmt"
    name = "shfmt"
    help = "An autoformatter for shell scripts (https://github.com/mvdan/sh)."

    default_version = "v3.6.0"
    default_known_versions = [
        "v3.2.4|macos_arm64 |e70fc42e69debe3e400347d4f918630cdf4bf2537277d672bbc43490387508ec|2998546",
        "v3.2.4|macos_x86_64|43a0461a1b54070ddc04fbbf1b78f7861ee39a65a61f5466d15a39c4aba4f917|2980208",
        "v3.2.4|linux_arm64 |6474d9cc08a1c9fe2ef4be7a004951998e3067d46cf55a011ddd5ff7bfab3de6|2752512",
        "v3.2.4|linux_x86_64|3f5a47f8fec27fae3e06d611559a2063f5d27e4b9501171dde9959b8c60a3538|2797568",
        "v3.6.0|macos_arm64 |633f242246ee0a866c5f5df25cbf61b6af0d5e143555aca32950059cf13d91e0|3065202",
        "v3.6.0|macos_x86_64|b8c9c025b498e2816b62f0b717f6032e9ab49e725a45b8205f52f66318f17185|3047552",
        "v3.6.0|linux_arm64 |fb1cf0af3dbe9aac7d98e38e3c7426765208ecfe23cb2da51037bb234776fd70|2818048",
        "v3.6.0|linux_x86_64|5741a02a641de7e56b8da170e71a97e58050d66a3cf485fb268d6a5a8bb74afb|2850816",
    ]

    default_url_template = (
        "https://github.com/mvdan/sh/releases/download/{version}/shfmt_{version}_{platform}"
    )
    default_url_platform_mapping = {
        "macos_arm64": "darwin_arm64",
        "macos_x86_64": "darwin_amd64",
        "linux_arm64": "linux_arm64",
        "linux_x86_64": "linux_amd64",
    }

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="-i 2")
    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=softwrap(
            """
            If true, Pants will include all relevant `.editorconfig` files during runs.
            See https://editorconfig.org.
            """
        ),
    )

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # Refer to https://editorconfig.org/#file-location for how config files are discovered.
        candidates = (os.path.join(d, ".editorconfig") for d in ("", *dirs))
        return ConfigFilesRequest(
            discovery=self.config_discovery,
            check_content={fp: b"[*.sh]" for fp in candidates},
        )
