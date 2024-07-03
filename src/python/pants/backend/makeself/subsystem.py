# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
import logging
from typing import Iterable, Optional

from pants.core.util_rules import external_tool
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    TemplatedExternalTool,
)
from pants.engine.fs import Digest
from pants.engine.fs import RemovePrefix
from pants.engine.platform import Platform
from pants.engine.rules import Rule, collect_rules, rule
from pants.core.util_rules.external_tool import download_external_tool
from pants.engine.process import fallible_to_exec_result_or_raise
from pants.engine.intrinsics import remove_prefix_request_to_digest
from pants.engine.rules import implicitly
from pants.util.logging import LogLevel
from pants.util.meta import classproperty

logger = logging.getLogger(__name__)


class MakeselfSubsystem(TemplatedExternalTool):
    options_scope = "makeself"
    help = "A tool to generate a self-extractable compressed tar archives."

    default_version = "2.5.0"

    @classproperty
    def default_known_versions(cls):
        return [
            "|".join(
                (
                    cls.default_version,
                    platform,
                    "4d2fa9d898be22c63bb3c6bb7cc3dc97237700dea6d6ad898dcbec0289df0bc4",
                    "45867",
                )
            )
            for platform in ["macos_arm64", "macos_x86_64", "linux_arm64", "linux_x86_64"]
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
    output_directory: Optional[str] = None
    extra_args: Optional[tuple[str, ...]] = None
    extra_tools: tuple[str, ...] = ()


@rule(desc="Extract makeself distribution", level=LogLevel.DEBUG)
async def extract_makeself_distribution(
    dist: MakeselfDistribution,
) -> MakeselfTool:
    out = "__makeself"
    result = await fallible_to_exec_result_or_raise(
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
    digest = await remove_prefix_request_to_digest(RemovePrefix(result.output_digest, out))
    return MakeselfTool(digest=digest, exe="makeself.sh")


def rules() -> Iterable[Rule]:
    return (
        *collect_rules(),
        *external_tool.rules(),
    )
