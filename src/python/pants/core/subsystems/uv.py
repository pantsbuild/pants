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

    default_version = "0.6.12"
    default_known_versions = [
        "0.6.12|linux_arm64|d867553e5ea19f9cea08e564179d909c69ecfce5e7e382099d1844dbf1c9878c|15675948",
        "0.6.12|linux_x86_64|eec3ccf53616e00905279a302bc043451bd96ca71a159a2ac3199452ac914c26|16790841",
        "0.6.12|macos_arm64|fab8db5b62da1e945524b8d1a9d4946fcc6d9b77ec0cab423d953e82159967ac|14966335",
        "0.6.12|macos_x86_64|5b6ee08766de11dc49ee9e292333e8b46ef2ceaaa3ebb0388467e114fca2ed8c|16124245",
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
