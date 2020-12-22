# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple

from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine.console import Console
from pants.engine.fs import Digest, MergeDigests, SpecsSnapshot
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, collect_rules, goal_rule
from pants.option.custom_types import shell_str
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class SuccinctCodeCounter(TemplatedExternalTool):
    options_scope = "scc"
    help = "The Succinct Code Counter, aka `scc` (https://github.com/boyter/scc)."

    default_version = "2.12.0"
    default_known_versions = [
        "2.12.0|darwin|70b7002cd1e4541cb37b7b9cbc0eeedd13ceacb49628e82ab46332bb2e65a5a6|1842530",
        "2.12.0|linux|8eca3e98fe8a78d417d3779a51724515ac4459760d3ec256295f80954a0da044|1753059",
    ]
    default_url_template = (
        "https://github.com/boyter/scc/releases/download/v{version}/scc-{version}-"
        "x86_64-{platform}.zip"
    )
    default_url_platform_mapping = {
        "darwin": "apple-darwin",
        "linux": "unknown-linux",
    }

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--args",
            type=list,
            member_type=shell_str,
            passthrough=True,
            help=(
                'Arguments to pass directly to SCC, e.g. `--count-loc-args="--no-cocomo"`. Refer '
                "to https://github.com/boyter/scc."
            ),
        )

    @property
    def args(self) -> Tuple[str, ...]:
        return tuple(self.options.args)

    def generate_exe(self, _: Platform) -> str:
        return "./scc"


class CountLinesOfCodeSubsystem(GoalSubsystem):
    name = "count-loc"
    help = "Count lines of code."


class CountLinesOfCode(Goal):
    subsystem_cls = CountLinesOfCodeSubsystem


@goal_rule
async def count_loc(
    console: Console,
    succinct_code_counter: SuccinctCodeCounter,
    specs_snapshot: SpecsSnapshot,
) -> CountLinesOfCode:
    if not specs_snapshot.snapshot.files:
        return CountLinesOfCode(exit_code=0)

    scc_program = await Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        succinct_code_counter.get_request(Platform.current),
    )
    input_digest = await Get(
        Digest, MergeDigests((scc_program.digest, specs_snapshot.snapshot.digest))
    )
    result = await Get(
        ProcessResult,
        Process(
            argv=(scc_program.exe, *succinct_code_counter.args),
            input_digest=input_digest,
            description=(
                f"Count lines of code for {pluralize(len(specs_snapshot.snapshot.files), 'file')}"
            ),
            level=LogLevel.DEBUG,
        ),
    )
    console.print_stdout(result.stdout.decode())
    return CountLinesOfCode(exit_code=0)


def rules():
    return collect_rules()
