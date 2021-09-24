# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine.fs import Digest
from pants.engine.platform import Platform
from pants.engine.rules import Get, collect_rules, rule


class GolangSubsystem(TemplatedExternalTool):
    options_scope = "golang"
    name = "golang"
    help = "Official golang distribution."

    default_version = "1.16.5"
    default_known_versions = [
        "1.16.5|macos_arm64 |7b1bed9b63d69f1caa14a8d6911fbd743e8c37e21ed4e5b5afdbbaa80d070059|125731583",
        "1.16.5|macos_x86_64|be761716d5bfc958a5367440f68ba6563509da2f539ad1e1864bd42fe553f277|130223787",
        "1.16.5|linux_x86_64|b12c23023b68de22f74c0524f10b753e7b08b1504cb7e417eccebdd3fae49061|129049763",
    ]
    default_url_template = "https://golang.org/dl/go{version}.{platform}.tar.gz"
    default_url_platform_mapping = {
        "macos_arm64": "darwin-arm64",
        "macos_x86_64": "darwin-amd64",
        "linux_x86_64": "linux-amd64",
    }

    def generate_exe(self, plat: Platform) -> str:
        return "./bin"


@dataclass(frozen=True)
class GoRoot:
    """Path to the Go installation (the `GOROOT`)."""

    path: str
    digest: Digest


@rule
async def setup_goroot(golang_subsystem: GolangSubsystem) -> GoRoot:
    downloaded_go_dist = await Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        golang_subsystem.get_request(Platform.current),
    )
    return GoRoot("./go", downloaded_go_dist.digest)


def rules():
    return collect_rules()
