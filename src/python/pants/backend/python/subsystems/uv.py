# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.core.util_rules.external_tool import (
    TemplatedExternalTool,
    download_external_tool,
)
from pants.engine.fs import Digest
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules, rule
from pants.option.option_types import ArgsListOption
from pants.util.strutil import softwrap


class Uv(TemplatedExternalTool):
    options_scope = "uv"
    name = "uv"
    help = "The uv Python package manager (https://github.com/astral-sh/uv)."

    default_version = "0.6.14"
    default_known_versions = [
        "0.6.14|macos_x86_64|1d8ecb2eb3b68fb50e4249dc96ac9d2458dc24068848f04f4c5b42af2fd26552|16276555",
        "0.6.14|macos_arm64|4ea4731010fbd1bc8e790e07f199f55a5c7c2c732e9b77f85e302b0bee61b756|15138933",
        "0.6.14|linux_x86_64|0cac4df0cb3457b154f2039ae471e89cd4e15f3bd790bbb3cb0b8b40d940b93e|17032361",
        "0.6.14|linux_arm64|94e22c4be44d205def456427639ca5ca1c1a9e29acc31808a7b28fdd5dcf7f17|15577079",
    ]
    version_constraints = ">=0.6.0,<1.0"

    default_url_template = (
        "https://github.com/astral-sh/uv/releases/download/{version}/uv-{platform}.tar.gz"
    )
    default_url_platform_mapping = {
        "linux_arm64": "aarch64-unknown-linux-musl",
        "linux_x86_64": "x86_64-unknown-linux-musl",
        "macos_arm64": "aarch64-apple-darwin",
        "macos_x86_64": "x86_64-apple-darwin",
    }

    def generate_exe(self, plat: Platform) -> str:
        platform = self.default_url_platform_mapping[plat.value]
        return f"./uv-{platform}/uv"

    args_for_uv_pip_install = ArgsListOption(
        tool_name="uv",
        example="--index-strategy unsafe-first-match",
        extra_help=softwrap(
            """
            Additional arguments to pass to `uv pip install` invocations.

            Used when `[python].pex_builder = "uv"` to pass extra flags to the
            `uv pip install` step (e.g. `--index-url`, `--extra-index-url`).
            These are NOT passed to the `uv venv` step.
            """
        ),
    )


@dataclass(frozen=True)
class DownloadedUv:
    """The downloaded uv binary with user-configured args."""

    digest: Digest
    exe: str
    args_for_uv_pip_install: tuple[str, ...]


@rule
async def download_uv_binary(uv: Uv, platform: Platform) -> DownloadedUv:
    downloaded = await download_external_tool(uv.get_request(platform))
    return DownloadedUv(digest=downloaded.digest, exe=downloaded.exe, args_for_uv_pip_install=tuple(uv.args_for_uv_pip_install))


def rules():
    return collect_rules()
