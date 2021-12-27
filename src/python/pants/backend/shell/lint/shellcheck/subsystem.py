# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from typing import Iterable, cast

from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.option.custom_types import shell_str


class Shellcheck(TemplatedExternalTool):
    options_scope = "shellcheck"
    help = "A linter for shell scripts."

    default_version = "v0.8.0"
    default_known_versions = [
        "v0.8.0|macos_arm64 |e065d4afb2620cc8c1d420a9b3e6243c84ff1a693c1ff0e38f279c8f31e86634|4049756",
        "v0.8.0|macos_x86_64|e065d4afb2620cc8c1d420a9b3e6243c84ff1a693c1ff0e38f279c8f31e86634|4049756",
        "v0.8.0|linux_arm64 |9f47bbff5624babfa712eb9d64ece14c6c46327122d0c54983f627ae3a30a4ac|2996468",
        "v0.8.0|linux_x86_64|ab6ee1b178f014d1b86d1e24da20d1139656c8b0ed34d2867fbb834dad02bf0a|1403852",
    ]

    default_url_template = (
        "https://github.com/koalaman/shellcheck/releases/download/{version}/shellcheck-"
        "{version}.{platform}.tar.xz"
    )
    default_url_platform_mapping = {
        "macos_arm64": "darwin.x86_64",
        "macos_x86_64": "darwin.x86_64",
        "linux_arm64": "linux.aarch64",
        "linux_x86_64": "linux.x86_64",
    }

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help="Don't use Shellcheck when running `./pants lint`.",
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            help=(
                "Arguments to pass directly to Shellcheck, e.g. `--shellcheck-args='-e SC20529'`.'"
            ),
        )
        register(
            "--config-discovery",
            type=bool,
            default=True,
            advanced=True,
            help=(
                "If true, Pants will include all relevant `.shellcheckrc` and `shellcheckrc` files "
                "during runs. See https://www.mankier.com/1/shellcheck#RC_Files for where these "
                "can be located."
            ),
        )

    def generate_exe(self, _: Platform) -> str:
        return f"./shellcheck-{self.version}/shellcheck"

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)

    @property
    def args(self) -> tuple[str, ...]:
        return tuple(self.options.args)

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # Refer to https://www.mankier.com/1/shellcheck#RC_Files for how config files are
        # discovered.
        candidates = []
        for d in ("", *dirs):
            candidates.append(os.path.join(d, ".shellcheckrc"))
            candidates.append(os.path.join(d, "shellcheckrc"))
        return ConfigFilesRequest(
            discovery=cast(bool, self.options.config_discovery), check_existence=candidates
        )
