# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from typing import Iterable

from pants.core.util_rules.config_files import ConfigFilesRequest
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import ArgsListOption, BoolOption, SkipOption
from pants.util.strutil import softwrap


class Shellcheck(TemplatedExternalTool):
    options_scope = "shellcheck"
    name = "Shellcheck"
    help = "A linter for shell scripts."

    default_version = "v0.10.0"
    default_known_versions = [
        "v0.10.0|macos_arm64 |bbd2f14826328eee7679da7221f2bc3afb011f6a928b848c80c321f6046ddf81|7205756",
        "v0.10.0|macos_x86_64|ef27684f23279d112d8ad84e0823642e43f838993bbb8c0963db9b58a90464c2|4371632",
        "v0.10.0|linux_arm64 |324a7e89de8fa2aed0d0c28f3dab59cf84c6d74264022c00c22af665ed1a09bb|4291764",
        "v0.10.0|linux_x86_64|6c881ab0698e4e6ea235245f22832860544f17ba386442fe7e9d629f8cbedf87|2404716",
    ]

    default_url_template = (
        "https://github.com/koalaman/shellcheck/releases/download/{version}/shellcheck-"
        "{version}.{platform}.tar.xz"
    )
    default_url_platform_mapping = {
        "macos_arm64": "darwin.aarch64",
        "macos_x86_64": "darwin.x86_64",
        "linux_arm64": "linux.aarch64",
        "linux_x86_64": "linux.x86_64",
    }

    skip = SkipOption("lint")
    args = ArgsListOption(example="-e SC20529")
    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=softwrap(
            """
            If true, Pants will include all relevant `.shellcheckrc` and `shellcheckrc` files
            during runs. See https://www.mankier.com/1/shellcheck#RC_Files for where these
            can be located.
            """
        ),
    )

    def generate_exe(self, _: Platform) -> str:
        return f"./shellcheck-{self.version}/shellcheck"

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # Refer to https://www.mankier.com/1/shellcheck#RC_Files for how config files are
        # discovered.
        candidates = []
        for d in ("", *dirs):
            candidates.append(os.path.join(d, ".shellcheckrc"))
            candidates.append(os.path.join(d, "shellcheckrc"))
        return ConfigFilesRequest(discovery=self.config_discovery, check_existence=candidates)
