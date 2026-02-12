# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules import external_tool
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    TemplatedExternalTool,
    download_external_tool,
)
from pants.engine.fs import Digest, RemovePrefix
from pants.engine.intrinsics import remove_prefix
from pants.engine.platform import Platform
from pants.engine.process import execute_process_or_raise
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class MakeselfSubsystem(TemplatedExternalTool):
    options_scope = "makeself"
    help = "A tool to generate a self-extractable compressed tar archives."

    default_version = "2.5.0"
    default_known_versions = [
        "2.5.0|linux_arm64 |4d2fa9d898be22c63bb3c6bb7cc3dc97237700dea6d6ad898dcbec0289df0bc4|45867",
        "2.5.0|linux_x86_64|4d2fa9d898be22c63bb3c6bb7cc3dc97237700dea6d6ad898dcbec0289df0bc4|45867",
        "2.5.0|macos_arm64 |4d2fa9d898be22c63bb3c6bb7cc3dc97237700dea6d6ad898dcbec0289df0bc4|45867",
        "2.5.0|macos_x86_64|4d2fa9d898be22c63bb3c6bb7cc3dc97237700dea6d6ad898dcbec0289df0bc4|45867",
    ]
    default_url_template = "https://github.com/megastep/makeself/releases/download/release-{version}/makeself-{version}.run"


class MakeselfDistribution(DownloadedExternalTool):
    """The makeself distribution.

    You can find releases here: https://github.com/megastep/makeself/releases
    """


@rule(desc="Download makeself distribution", level=LogLevel.DEBUG)
async def download_makeself_distribution(
    options: MakeselfSubsystem,
    platform: Platform,
) -> MakeselfDistribution:
    tool = await download_external_tool(options.get_request(platform))
    logger.debug("makeself external tool: %s", tool)
    return MakeselfDistribution(digest=tool.digest, exe=tool.exe)


class MakeselfTool(DownloadedExternalTool):
    """The Makeself tool."""


@dataclass(frozen=True)
class RunMakeselfArchive:
    exe: str
    input_digest: Digest
    description: str
    level: LogLevel = LogLevel.INFO
    output_directory: str | None = None
    extra_args: tuple[str, ...] | None = None
    extra_tools: tuple[str, ...] = ()


@rule(desc="Extract makeself distribution", level=LogLevel.DEBUG)
async def extract_makeself_distribution(
    dist: MakeselfDistribution,
) -> MakeselfTool:
    out = "__makeself"
    result = await execute_process_or_raise(
        **implicitly(
            RunMakeselfArchive(
                exe=dist.exe,
                extra_args=(
                    "--keep",
                    "--accept",
                    "--noprogress",
                    "--nox11",
                    "--nochown",
                    "--nodiskspace",
                    "--quiet",
                ),
                input_digest=dist.digest,
                output_directory=out,
                description=f"Extracting Makeself archive: {out}",
                level=LogLevel.DEBUG,
            )
        )
    )
    digest = await remove_prefix(RemovePrefix(result.output_digest, out))
    return MakeselfTool(digest=digest, exe="makeself.sh")


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *external_tool.rules(),
        UnionRule(ExportableTool, MakeselfSubsystem),
    )
