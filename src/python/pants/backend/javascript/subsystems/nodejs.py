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
from pants.engine.fs import EMPTY_DIGEST, Digest, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import Process
from pants.engine.rules import Get, Rule, SubsystemRule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


class NodeJS(TemplatedExternalTool):
    options_scope = "nodejs"
    help = "The NodeJS Javascript runtime (including npm and npx)."

    # TODO: Update to latest LTS
    default_version = "v16.14.1"
    default_known_versions = [
        "v16.14.1|macos_arm64|8f6d45796f3d996484dcf53bb0e53cd019cd0ef7a1a247bd0178ebaa7e63a184|28983951",
        "v16.14.1|macos_x86_64|af35abd727b051c8cdb8dcda9815ae93f96ef2c224d71f4ec52034a2ab5d8b61|30414480",
        "v16.14.1|linux_arm64|53aeda7118cd1991424b457907790033326f432ee6c2908a7693920124622cf4|32852829",
        "v16.14.1|linux_x86_64|8db3d6d8ecfc2af932320fb12449de2b5b76f946ac72b47c6a9074afe82737ff|32861678",
    ]

    default_url_template = "https://nodejs.org/dist/{version}/node-{version}-{platform}.tar.gz"
    default_url_platform_mapping = {
        "macos_arm64": "darwin-arm64",
        "macos_x86_64": "darwin-x64",
        "linux_arm64": "linux-arm64",
        "linux_x86_64": "linux-x64",
    }

    def generate_exe(self, plat: Platform) -> str:
        assert self.default_url_platform_mapping is not None
        plat_str = self.default_url_platform_mapping[plat.value]
        return f"./node-{self.version}-{plat_str}/bin/node"


@dataclass(frozen=True)
class NpxProcess:
    """A request to invoke the npx cli (via NodeJS)"""

    npm_package: str
    argv: tuple[str, ...]
    description: str
    input_digest: Digest = EMPTY_DIGEST
    output_files: tuple[str, ...] = ()


@rule(level=LogLevel.DEBUG)
async def setup_npx_process(request: NpxProcess, nodejs: NodeJS) -> Process:
    # Ensure nodejs is installed
    downloaded_nodejs = await Get(
        DownloadedExternalTool, ExternalToolRequest, nodejs.get_request(Platform.current)
    )

    input_digest = await Get(Digest, MergeDigests((request.input_digest, downloaded_nodejs.digest)))

    # Get reference to npx
    assert nodejs.default_url_platform_mapping is not None
    plat_str = nodejs.default_url_platform_mapping[Platform.current.value]
    nodejs_dir = f"node-{nodejs.version}-{plat_str}"
    # TODO: This is a bit garbage, because the /bin/npx tries to load from the system node
    npx_exe = (
        downloaded_nodejs.exe,
        f"./{nodejs_dir}/lib/node_modules/npm/bin/npx-cli.js",
        "--yes",
    )

    return Process(
        argv=(
            *npx_exe,
            request.npm_package,
            *request.argv,
        ),
        input_digest=input_digest,
        output_files=request.output_files,
        description=request.description,
        level=LogLevel.DEBUG,
        env={"PATH": f"/bin:./{nodejs_dir}/bin"},
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        SubsystemRule(NodeJS),
    )
