# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass, field
from typing import ClassVar, Iterable, Mapping

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
from pants.option.option_types import DictOption
from pants.util.docutil import bin_name
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


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

    resolves = DictOption[str](
        default={},
        help=softwrap(
            f"""
            A mapping of names to lockfile paths used in your project.

            Specifying a resolve name is optional. If unspecified,
            the default resolve name is calculated by taking the path
            from the source root to the directory containing the lockfile
            and replacing '{os.path.sep}' with '.' in that path.

            Example:
            An npm lockfile located at `src/js/package/package-lock.json'
            will result in a resolve named `js.package`, assuming src/
            is a source root.

            Run `{bin_name()} generate-lockfiles` to
            generate the lockfile(s).
            """
        ),
        advanced=True,
    )

    def generate_url(self, plat: Platform) -> str:
        """NodeJS binaries are compressed as .gz for Mac, .xz for Linux."""
        url = super().generate_url(plat)
        extension = "gz" if plat.is_macos else "xz"
        return f"{url}.{extension}"

    def generate_exe(self, plat: Platform) -> str:
        assert self.default_url_platform_mapping is not None
        plat_str = self.default_url_platform_mapping[plat.value]
        return f"./node-{self.version}-{plat_str}/bin/node"


class UserChosenNodeJSResolveAliases(FrozenDict[str, str]):
    pass


@rule(level=LogLevel.DEBUG)
async def user_chosen_resolve_aliases(nodejs: NodeJS) -> UserChosenNodeJSResolveAliases:
    return UserChosenNodeJSResolveAliases((value, key) for key, value in nodejs.resolves.items())


@dataclass(frozen=True)
class NodeJSToolProcess:
    """A request for a tool installed with NodeJs."""

    args: tuple[str, ...]
    description: str
    level: LogLevel = LogLevel.INFO
    input_digest: Digest = EMPTY_DIGEST
    output_files: tuple[str, ...] = ()
    output_directories: tuple[str, ...] = ()
    working_directory: str | None = None
    append_only_caches: FrozenDict[str, str] = field(default_factory=FrozenDict)

    @classmethod
    def npm(
        cls,
        args: Iterable[str],
        description: str,
        level: LogLevel = LogLevel.INFO,
        input_digest: Digest = EMPTY_DIGEST,
        output_files: tuple[str, ...] = (),
        output_directories: tuple[str, ...] = (),
        working_directory: str | None = None,
        append_only_caches: FrozenDict[str, str] | None = None,
    ) -> NodeJSToolProcess:
        return cls(
            args=("npm", *args),
            description=description,
            level=level,
            input_digest=input_digest,
            output_files=output_files,
            output_directories=output_directories,
            working_directory=working_directory,
            append_only_caches=append_only_caches or FrozenDict(),
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
            "PATH": f"/bin:{self.binary_directory}",
            "npm_config_cache": self.npm_config_cache,  # Normally stored at ~/.npm
        }

    @property
    def append_only_caches(self) -> Mapping[str, str]:
        return {"npm": self.npm_config_cache}


@rule(level=LogLevel.DEBUG)
async def node_process_environment(nodejs: NodeJS, platform: Platform) -> NodeJSProcessEnvironment:
    # Get reference to tool
    assert nodejs.default_url_platform_mapping is not None
    plat_str = nodejs.default_url_platform_mapping[platform.value]
    nodejs_bin_dir = os.path.join(
        "{chroot}",
        NodeJSProcessEnvironment.base_bin_dir,
        f"node-{nodejs.version}-{plat_str}",
        "bin",
    )

    return NodeJSProcessEnvironment(binary_directory=nodejs_bin_dir, npm_config_cache="._npm")


@dataclass(frozen=True)
class NodejsBinaries:
    digest: Digest


@rule(level=LogLevel.INFO, desc="Determining nodejs binaries.")
async def determine_nodejs_binaries(nodejs: NodeJS, platform: Platform) -> NodejsBinaries:
    downloaded = await Get(
        DownloadedExternalTool, ExternalToolRequest, nodejs.get_request(platform)
    )
    return NodejsBinaries(downloaded.digest)


@rule(level=LogLevel.DEBUG)
async def setup_node_tool_process(
    request: NodeJSToolProcess, binaries: NodejsBinaries, environment: NodeJSProcessEnvironment
) -> Process:
    immutable_input_digests = {environment.base_bin_dir: binaries.digest}

    return Process(
        argv=filter(None, request.args),
        input_digest=request.input_digest,
        output_files=request.output_files,
        immutable_input_digests=immutable_input_digests,
        output_directories=request.output_directories,
        description=request.description,
        level=request.level,
        env=environment.to_env_dict(),
        working_directory=request.working_directory,
        append_only_caches={**request.append_only_caches, **environment.append_only_caches},
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *external_tool_rules(),
    )
