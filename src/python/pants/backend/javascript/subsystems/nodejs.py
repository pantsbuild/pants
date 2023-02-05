# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass
from typing import Iterable, ClassVar

from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import EMPTY_DIGEST, Digest
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
class NodeJSToolProcess:
    """A request for a tool installed with NodeJs."""

    args: tuple[str, ...]
    description: str
    level: LogLevel = LogLevel.INFO
    input_digest: Digest = EMPTY_DIGEST
    output_files: tuple[str, ...] = ()
    output_directories: tuple[str, ...] = ()

    @classmethod
    def npm(
        cls,
        args: Iterable[str],
        description: str,
        level: LogLevel = LogLevel.INFO,
        input_digest: Digest = EMPTY_DIGEST,
        output_files: tuple[str, ...] = (),
        output_directories: tuple[str, ...] = (),
    ) -> NodeJSToolProcess:
        return cls(
            args=("npm", *args),
            description=description,
            level=level,
            input_digest=input_digest,
            output_files=output_files,
            output_directories=output_directories,
        )

    @classmethod
    def npx(
        cls,
        args: Iterable[str],
        npm_package: str,
        description: str,
        level: LogLevel = LogLevel.INFO,
        input_digest: Digest = EMPTY_DIGEST,
        output_files: tuple[str, ...] = (),
    ) -> NodeJSToolProcess:
        return cls(
            args=("npx", "--yes", npm_package, *args),
            description=description,
            level=level,
            input_digest=input_digest,
            output_files=output_files,
        )


@dataclass(frozen=True)
class NodeJSProcessEnvironment:
    binary_directory: str
    npm_config_cache: str

    base_bin_dir: ClassVar[str] = "__node"

    def to_env_dict(self) -> dict[str, str]:
        return {
            "PATH": os.path.pathsep.join((os.path.join(os.path.sep, "bin"), self.binary_directory)),
            "npm_config_cache": self.npm_config_cache,  # Normally stored at ~/.npm
        }


@rule(level=LogLevel.DEBUG)
async def node_process_environment(
    nodejs: NodeJS, platform: Platform, named_caches_dir: NamedCachesDirOption
) -> NodeJSProcessEnvironment:
    # Get reference to tool
    assert nodejs.default_url_platform_mapping is not None
    plat_str = nodejs.default_url_platform_mapping[platform.value]
    nodejs_bin_dir = os.path.join(
        "{chroot}", NodeJSProcessEnvironment.base_bin_dir, f"node-{nodejs.version}-{plat_str}", "bin"
    )

    return NodeJSProcessEnvironment(
        binary_directory=nodejs_bin_dir,
        npm_config_cache=str(named_caches_dir.val / "npm")
    )


@rule(level=LogLevel.DEBUG)
async def setup_node_tool_process(
    request: NodeJSToolProcess,
    nodejs: NodeJS,
    platform: Platform,
    environment: NodeJSProcessEnvironment,
) -> Process:
    # Ensure nodejs is installed
    downloaded_nodejs = await Get(
        DownloadedExternalTool, ExternalToolRequest, nodejs.get_request(platform)
    )

    immutable_input_digests = {NodeJSProcessEnvironment.base_bin_dir: downloaded_nodejs.digest}

    return Process(
        argv=filter(None, request.args),
        input_digest=request.input_digest,
        output_files=request.output_files,
        immutable_input_digests=immutable_input_digests,
        output_directories=request.output_directories,
        description=request.description,
        level=request.level,
        env=environment.to_env_dict(),
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *external_tool_rules(),
    )
