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

    default_version = "0.6.15"
    default_known_versions = [
        "0.6.15|macos_x86_64|97adf61511c0f6ea42c090443c38d8d71116b78ae626363f9f149924c91ae886|16612743",
        "0.6.15|macos_arm64|1c5b25f75c6438b6910dbc4c6903debe53f31ee14aee55d02243dfe7bf7c9f72|15356260",
        "0.6.15|linux_x86_64|78289c93836cb32b8b24e3216b5b316e7fdf483365de2fc571844d308387e8a4|17337856",
        "0.6.15|linux_arm64|183cebae8c9d91bbd48219f9006a5c0c41c90a075d6724aec53a7ea0503c665a|15820802",
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
    return DownloadedUv(
        digest=downloaded.digest,
        exe=downloaded.exe,
        args_for_uv_pip_install=tuple(uv.args_for_uv_pip_install),
    )


def rules():
    return collect_rules()
