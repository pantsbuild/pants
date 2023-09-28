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

    default_version = "v0.8.0"
    default_known_versions = [
        "v0.8.0|macos_arm64 |36dffd536b801c8bab2e9fa468163037e0c7f7e0a05298e5ad6299b4dde67e31|14525367",
        "v0.8.0|macos_x86_64|4e93a76ee116b2f08c88e25011830280ad0d61615d8346364a4ea564b29be3f0|6310442",
        "v0.8.0|linux_arm64 |8f4810485425636eadce2ec23441fd29d5b1b58d239ffda0a5faf8dd499026f5|4884430",
        "v0.8.0|linux_x86_64|01d181787ffe63ebb0a2293f63bdc8455c5c30d3a6636320664bfa278424638f|2082242",
    ]

    # We use this third party source since it has pre-compiled binaries for both x86 and aarch.
    # It is recommended by shellcheck
    # https://github.com/koalaman/shellcheck/blob/90d3172dfec30a7569f95b32479ae97af73b8b2e/README.md?plain=1#L236-L237
    default_url_template = (
        "https://github.com/vscode-shellcheck/shellcheck-binaries/releases/download/{version}/shellcheck-"
        "{version}.{platform}.tar.gz"
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
        return "./shellcheck"

    def config_request(self, dirs: Iterable[str]) -> ConfigFilesRequest:
        # Refer to https://www.mankier.com/1/shellcheck#RC_Files for how config files are
        # discovered.
        candidates = []
        for d in ("", *dirs):
            candidates.append(os.path.join(d, ".shellcheckrc"))
            candidates.append(os.path.join(d, "shellcheckrc"))
        return ConfigFilesRequest(discovery=self.config_discovery, check_existence=candidates)
