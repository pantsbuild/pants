# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from typing import Iterable, cast

from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.option.custom_types import shell_str


class Shfmt(TemplatedExternalTool):
    options_scope = "shfmt"
    help = "An autoformatter for shell scripts (https://github.com/mvdan/sh)."

    default_version = "v3.2.4"
    default_known_versions = [
        "v3.2.4|macos_arm64 |e70fc42e69debe3e400347d4f918630cdf4bf2537277d672bbc43490387508ec|2998546",
        "v3.2.4|macos_x86_64|43a0461a1b54070ddc04fbbf1b78f7861ee39a65a61f5466d15a39c4aba4f917|2980208",
        "v3.2.4|linux_arm64 |6474d9cc08a1c9fe2ef4be7a004951998e3067d46cf55a011ddd5ff7bfab3de6|2752512",
        "v3.2.4|linux_x86_64|3f5a47f8fec27fae3e06d611559a2063f5d27e4b9501171dde9959b8c60a3538|2797568",
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

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help="Don't use shfmt when running `./pants fmt` and `./pants lint`.",
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help="Arguments to pass directly to shfmt, e.g. `--shfmt-args='-i 2'`.'",
        )
        register(
            "--config-discovery",
            type=bool,
            default=True,
            advanced=True,
            help=(
                "If true, Pants will include all relevant `.editorconfig` files during runs. "
                "See https://editorconfig.org."
            ),
        )

    def generate_exe(self, plat: Platform) -> str:
        plat_str = self.default_url_platform_mapping[plat.value]
        return f"./shfmt_{self.version}_{plat_str}"

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> tuple[str, ...]:
        return tuple(self.options.args)

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # Refer to https://editorconfig.org/#file-location for how config files are discovered.
        candidates = (os.path.join(d, ".editorconfig") for d in ("", *dirs))
        return ConfigFilesRequest(
            discovery=cast(bool, self.options.config_discovery),
            check_content={fp: b"[*.sh]" for fp in candidates},
        )
