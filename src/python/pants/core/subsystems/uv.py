# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules import external_tool
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

    default_version = "0.7.2"
    default_known_versions = [
        "0.7.2|linux_arm64|2872fdf4785666575d129ba90590c44e6508e22584735f3e7e8a30d773dfc3db|16239004",
        "0.7.2|linux_x86_64|cfaab1b5166a6439ff66f020333d3a12bbdf622deee3b510718283e8f06c9de7|17399523",
        "0.7.2|macos_arm64|8edc0bea8a9e35409f970b352036326393e79a6039577d8cc9ef63872c178a99|15536108",
        "0.7.2|macos_x86_64|7d30b59d54900c97c492f3c07ff21cc3387a9e5bd8ca6db2d502462eaaeefd68|16757236",
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

    def generate_exe(self, plat: Platform) -> str:
        platform = self.url_platform_mapping.get(plat.value, "")
        return f"./uv-{platform}/uv"


class UvTool(DownloadedExternalTool):
    """The UV tool, downloaded."""


@rule
async def download_uv_tool(uv_subsystem: UvSubsystem, platform: Platform) -> UvTool:
    pex_pex = await Get(
        DownloadedExternalTool, ExternalToolRequest, uv_subsystem.get_request(platform)
    )
    return UvTool(digest=pex_pex.digest, exe=pex_pex.exe)


def rules():
    return (
        *collect_rules(),
        *external_tool.rules(),
    )
