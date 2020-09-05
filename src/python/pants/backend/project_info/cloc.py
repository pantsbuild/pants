# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple

from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalTool,
    ExternalToolRequest,
)
from pants.engine.console import Console
from pants.engine.fs import Digest, MergeDigests, SourcesSnapshot
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, collect_rules, goal_rule
from pants.option.custom_types import shell_str
from pants.util.enums import match
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class ClocBinary(ExternalTool):
    """The SCC lines-of-code counter (https://github.com/boyter/scc)."""

    options_scope = "cloc-binary"
    name = "cloc"
    default_version = "2.12.0"
    default_known_versions = [
        "2.12.0|darwin|70b7002cd1e4541cb37b7b9cbc0eeedd13ceacb49628e82ab46332bb2e65a5a6|1842530",
        "2.12.0|linux|8eca3e98fe8a78d417d3779a51724515ac4459760d3ec256295f80954a0da044|1753059",
    ]

    def generate_url(self, plat: Platform) -> str:
        plat_str = match(plat, {Platform.darwin: "apple-darwin", Platform.linux: "unknown-linux"})
        return (
            f"https://github.com/boyter/scc/releases/download/v{self.version}/scc-{self.version}-"
            f"x86_64-{plat_str}.zip"
        )

    def generate_exe(self, _: Platform) -> str:
        return "./scc"


class CountLinesOfCodeSubsystem(GoalSubsystem):
    """Count lines of code using the SCC program (https://github.com/boyter/scc)."""

    name = "cloc"

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--ignored",
            type=bool,
            default=False,
            help="Show information about files ignored by cloc.",
            removal_version="2.1.0.dev0",
            removal_hint=(
                "This option no longer does anything, as we switched the cloc implementation from "
                "the `cloc` Perl script to SCC (Succinct Code Counter). Instead, use "
                "`--cloc-args='-v'` to see what SCC skips."
            ),
        )
        register(
            "--args",
            type=list,
            member_type=shell_str,
            passthrough=True,
            help=(
                'Arguments to pass directly to SCC, e.g. `--cloc-args="--no-cocomo"`. Refer to '
                "https://github.com/boyter/scc."
            ),
        )

    @property
    def args(self) -> Tuple[str, ...]:
        return tuple(self.options.args)


class CountLinesOfCode(Goal):
    subsystem_cls = CountLinesOfCodeSubsystem


@goal_rule
async def run_cloc(
    console: Console,
    cloc_subsystem: CountLinesOfCodeSubsystem,
    cloc_binary: ClocBinary,
    sources_snapshot: SourcesSnapshot,
) -> CountLinesOfCode:
    if not sources_snapshot.snapshot.files:
        return CountLinesOfCode(exit_code=0)

    scc_program = await Get(
        DownloadedExternalTool, ExternalToolRequest, cloc_binary.get_request(Platform.current)
    )
    input_digest = await Get(
        Digest, MergeDigests((scc_program.digest, sources_snapshot.snapshot.digest))
    )
    result = await Get(
        ProcessResult,
        Process(
            argv=(scc_program.exe, *cloc_subsystem.args),
            input_digest=input_digest,
            description=(
                f"Count lines of code for {pluralize(len(sources_snapshot.snapshot.files), 'file')}"
            ),
            level=LogLevel.DEBUG,
        ),
    )
    console.print_stdout(result.stdout.decode())
    return CountLinesOfCode(exit_code=0)


def rules():
    return collect_rules()
