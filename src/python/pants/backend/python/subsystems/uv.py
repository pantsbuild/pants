# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption
from pants.util.strutil import softwrap


class Uv(TemplatedExternalTool):
    options_scope = "uv"
    name = "uv"
    help = "The uv Python package manager (https://github.com/astral-sh/uv)."

    default_version = "0.9.5"
    default_known_versions = [
        "0.9.5|macos_x86_64|58b1d4a25aa8ff99147c2550b33dcf730207fe7e0f9a0d5d36a1bbf36b845aca|19689319",
        "0.9.5|macos_arm64|dc098ff224d78ed418e121fd374f655949d2c7031a70f6f6604eaf016a130433|18341942",
        "0.9.5|linux_x86_64|3665ffb6c429c31ad6c778ac0489b7746e691acf025cf530b3510b2f9b1660ff|21566106",
        "0.9.5|linux_arm64|42b9b83933a289fe9c0e48f4973dee49ce0dfb95e19ea0b525ca0dbca3bce71f|20079609",
    ]
    version_constraints = ">=0.0.0,<1"

    default_url_template = (
        "https://github.com/astral-sh/uv/releases/download/{version}/uv-{platform}.tar.gz"
    )
    default_url_platform_mapping = {
        # NB. Prefer musl over gnu, for increased compatibility.
        "linux_arm64": "aarch64-unknown-linux-musl",
        "linux_x86_64": "x86_64-unknown-linux-musl",
        "macos_arm64": "aarch64-apple-darwin",
        "macos_x86_64": "x86_64-apple-darwin",
    }

    def generate_exe(self, plat: Platform) -> str:
        platform = self.default_url_platform_mapping[plat.value]
        return f"./uv-{platform}/uv"

    args = ArgsListOption(
        passthrough=True,
        tool_name="uv pip compile",
        example="--index-strategy unsafe-first-match --resolution lowest-direct",
        extra_help=softwrap(
            """
            Only used when `[python].lockfile_resolver = "uv"`.

            For example, to prefer the first index that provides a given package, set:

                [uv]
                args = ["--index-strategy", "unsafe-first-match"]
            """
        ),
    )


def rules():
    return [*collect_rules(), UnionRule(ExportableTool, Uv)]
