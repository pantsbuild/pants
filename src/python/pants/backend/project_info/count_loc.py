# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


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
from pants.option.option_types import ArgsListOption
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class SuccinctCodeCounter(TemplatedExternalTool):
    options_scope = "scc"
    name = "SCC"
    help = "The Succinct Code Counter, aka `scc` (https://github.com/boyter/scc)."

    default_version = "3.0.0"
    default_known_versions = [
        "3.0.0|macos_arm64 |846cb1b25025a0794d455719bc17cfb3f588576a58af1d95036f6c654e294f98|2006145",
        "3.0.0|macos_x86_64|9c3064e477ab36e16204ad34f649372034bca4df669615eff5de4aa05b2ddf1a|2048134",
        "3.0.0|linux_arm64 |04f9e797b70a678833e49df5e744f95080dfb7f963c0cd34f5b5d4712d290f33|1768037",
        "3.0.0|linux_x86_64|13ca47ce00b5bd032f97f3af7aa8eb3c717b8972b404b155a378b09110e4aa0c|1948341",
    ]
    default_url_template = (
        "https://github.com/boyter/scc/releases/download/v{version}/scc-{version}-{platform}.zip"
    )
    default_url_platform_mapping = {
        "macos_arm64": "arm64-apple-darwin",
        "macos_x86_64": "x86_64-apple-darwin",
        "linux_arm64": "arm64-unknown-linux",
        "linux_x86_64": "x86_64-unknown-linux",
    }

    args = ArgsListOption(
        example="--no-cocomo",
        passthrough=True,
        extra_help="Refer to to https://github.com/boyter/scc.",
    )

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
