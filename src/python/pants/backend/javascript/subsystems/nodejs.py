# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import EMPTY_DIGEST, Digest, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import Process
from pants.engine.rules import Get, Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.global_options import NamedCachesDirOption
from pants.util.logging import LogLevel


class NodeJS(TemplatedExternalTool):
    options_scope = "nodejs"
    help = "The NodeJS Javascript runtime (including npm and npx)."

    default_version = "v16.15.0"
    default_known_versions = [
        "v16.15.0|macos_arm64|ad8d8fc5330ef47788f509c2af398c8060bb59acbe914070d0df684cd2d8d39b|29126014",
        "v16.15.0|macos_x86_64|a6bb12bbf979d32137598e49d56d61bcddf8a8596c3442b44a9b3ace58dd4de8|30561503",
        "v16.15.0|linux_arm64|b4080b86562c5397f32da7a0723b95b1df523cab4c757688a184e3f733a7df56|21403276",
        "v16.15.0|linux_x86_64|ebdf4dc9d992d19631f0931cca2fc33c6d0d382543639bc6560d31d5060a8372|22031988",
    ]

    default_url_template = "https://nodejs.org/dist/{version}/node-{version}-{platform}.tar"
    default_url_platform_mapping = {
        "macos_arm64": "darwin-arm64",
        "macos_x86_64": "darwin-x64",
        "linux_arm64": "linux-arm64",
        "linux_x86_64": "linux-x64",
    }

    def generate_url(self, plat: Platform) -> str:
        """NodeJS binaries are compressed as .gz for Mac, .xz for Linux."""
        url = super().generate_url(plat)
        extension = "gz" if plat.is_macos else "xz"
        return f"{url}.{extension}"

    def generate_exe(self, plat: Platform) -> str:
        assert self.default_url_platform_mapping is not None
        plat_str = self.default_url_platform_mapping[plat.value]
        return f"./node-{self.version}-{plat_str}/bin/node"


@dataclass(frozen=True)
class NpxProcess:
    """A request to invoke the npx cli (via NodeJS)"""

    npm_package: str
    args: tuple[str, ...]
    description: str
    level: LogLevel = LogLevel.INFO
    input_digest: Digest = EMPTY_DIGEST
    output_files: tuple[str, ...] = ()


@rule(level=LogLevel.DEBUG)
async def setup_npx_process(
    request: NpxProcess,
    nodejs: NodeJS,
    named_caches_dir: NamedCachesDirOption,
    platform: Platform,
) -> Process:
    # Ensure nodejs is installed
    downloaded_nodejs = await Get(
        DownloadedExternalTool, ExternalToolRequest, nodejs.get_request(platform)
    )

    input_digest = await Get(Digest, MergeDigests((request.input_digest, downloaded_nodejs.digest)))

    # Get reference to npx
    assert nodejs.default_url_platform_mapping is not None
    plat_str = nodejs.default_url_platform_mapping[platform.value]
    nodejs_dir = f"node-{nodejs.version}-{plat_str}"
    # TODO: Investigate if ./{nodejs_dir}/bin/npx can work - as that will be more stable in the long-term
    npx_exe = (
        downloaded_nodejs.exe,
        f"./{nodejs_dir}/lib/node_modules/npm/bin/npx-cli.js",
        "--yes",
    )

    argv = (
        *npx_exe,
        request.npm_package,
        *request.args,
    )
    # Argv represents NPX executable + NPM package name/version + NPM package args
    return Process(
        argv=filter(None, argv),
        input_digest=input_digest,
        output_files=request.output_files,
        description=request.description,
        level=request.level,
        env={
            "PATH": f"/bin:./{nodejs_dir}/bin",
            "npm_config_cache": str(named_caches_dir.val / "npm"),  # Normally stored at ~/.npm
        },
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *external_tool_rules(),
    )
