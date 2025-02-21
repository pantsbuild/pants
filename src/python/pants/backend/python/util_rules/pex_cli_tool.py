# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules import external_tool
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine.platform import Platform
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption
from pants.util.meta import classproperty
from pants.util.strutil import softwrap

# Note: These rules were separated from `pex_cli.py` so that the plugin resolution code in
# src/python/pants/init/plugin_resolver.py can rely on a downloaded `pex` tool without
# bringing in other parts of the Python backend.


class PexCli(TemplatedExternalTool):
    options_scope = "pex-cli"
    name = "pex"
    help = "The PEX (Python EXecutable) tool (https://github.com/pex-tool/pex)."

    default_version = "v2.33.1"
    default_url_template = "https://github.com/pex-tool/pex/releases/download/{version}/pex"
    version_constraints = ">=2.13.0,<3.0"

    # extra args to be passed to the pex tool; note that they
    # are going to apply to all invocations of the pex tool.
    global_args = ArgsListOption(
        example="--check=error --no-compile",
        extra_help=softwrap(
            """
            Note that these apply to all invocations of the pex tool, including building `pex_binary`
            targets, preparing `python_test` targets to run, and generating lockfiles.
            """
        ),
    )

    @classproperty
    def default_known_versions(cls):
        return [
            "|".join(
                (
                    cls.default_version,
                    plat,
                    "5ebed0e2ba875983a72b4715ee3b2ca6ae5fedbf28d738634e02e30e3bb5ed28",
                    "4559974",
                )
            )
            for plat in ["macos_arm64", "macos_x86_64", "linux_x86_64", "linux_arm64"]
        ]


class PexPEX(DownloadedExternalTool):
    """The Pex PEX binary."""


@rule
async def download_pex_pex(pex_cli: PexCli, platform: Platform) -> PexPEX:
    pex_pex = await Get(DownloadedExternalTool, ExternalToolRequest, pex_cli.get_request(platform))
    return PexPEX(digest=pex_pex.digest, exe=pex_pex.exe)


def rules():
    return (
        *collect_rules(),
        *external_tool.rules(),
        UnionRule(ExportableTool, PexCli),
    )
