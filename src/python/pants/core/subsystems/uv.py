# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine.platform import Platform
from pants.engine.rules import Get, collect_rules, rule


class UvSubsystem(TemplatedExternalTool):
    options_scope = "uv"
    name = "uv"
    help = "UV, An extremely fast Python package and project manager, written in Rust  (https://docs.astral.sh/uv/)"

    default_version = "0.6.2"
    default_known_versions = [
        "0.6.2|linux_arm64|ca4c08724764a2b6c8f2173c4e3ca9dcde0d9d328e73b4d725cfb6b17a925eed|15345219",
        "0.6.2|linux_x86_64|37ea31f099678a3bee56f8a757d73551aad43f8025d377a8dde80dd946c1b7f2|16399655",
        "0.6.2|macos_arm64|4af802a1216053650dd82eee85ea4241994f432937d41c8b0bc90f2639e6ae14|14608217",
        "0.6.2|macos_x86_64|2b9e78b2562aea93f13e42df1177cb07c59a4d4f1c8ff8907d0c31f3a5e5e8db|15658458",
    ]
    default_url_template = (
        "https://github.com/astral-sh/uv/releases/download/{version}/uv-{platform}.tar.gz"
    )
    default_url_platform_mapping = {
        "linux_arm64": "aarch64-unknown-linux-gnu",
        "linux_x86_64": "x86_64-unknown-linux-gnu",
        "macos_arm64": "aarch64-apple-darwin",
        "macos_x86_64": "x86_64-apple-darwin",
    }


class UvTool(DownloadedExternalTool):
    """The UV tool, downloaded."""


@rule
async def download_uv_tool(uv_subsystem: UvSubsystem, platform: Platform) -> UvTool:
    pex_pex = await Get(
        DownloadedExternalTool, ExternalToolRequest, uv_subsystem.get_request(platform)
    )
    return UvTool(digest=pex_pex.digest, exe=pex_pex.exe)


def rules():
    return collect_rules()
