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

    default_version = "v0.7.1"
    default_known_versions = [
        f"{default_version}|darwin|b080c3b659f7286e27004aa33759664d91e15ef2498ac709a452445d47e3ac23|1348272",
        f"{default_version}|linux|64f17152d96d7ec261ad3086ed42d18232fcb65148b44571b564d688269d36c8|1443836",
    ]

    default_url_template = (
        "https://github.com/koalaman/shellcheck/releases/download/{version}/shellcheck-"
        "{version}.{platform}.x86_64.tar.xz"
    )
    default_url_platform_mapping = {"darwin": "darwin", "linux": "linux"}

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
