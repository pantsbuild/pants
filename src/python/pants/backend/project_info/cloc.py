# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from dataclasses import dataclass

from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalTool,
    ExternalToolRequest,
)
from pants.engine.console import Console
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    MergeDigests,
    SingleFileExecutable,
    SourcesSnapshots,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import SubsystemRule, goal_rule
from pants.engine.selectors import Get
from pants.util.strutil import pluralize


class ClocBinary(ExternalTool):
    options_scope = "cloc-binary"
    name = "cloc"
    default_version = "1.80"
    default_known_versions = [
        "1.80|darwin|2b23012b1c3c53bd6b9dd43cd6aa75715eed4feb2cb6db56ac3fbbd2dffeac9d|546279",
        "1.80|linux |2b23012b1c3c53bd6b9dd43cd6aa75715eed4feb2cb6db56ac3fbbd2dffeac9d|546279",
    ]

    def generate_url(self, plat: Platform) -> str:
        version = self.get_options().version
        return f"https://github.com/AlDanial/cloc/releases/download/{version}/cloc-{version}.pl"


@dataclass(frozen=True)
class DownloadedClocScript:
    """Cloc script as downloaded from the pantsbuild binaries repo."""

    exe: SingleFileExecutable

    @property
    def script_path(self) -> str:
        return self.exe.exe_filename

    @property
    def digest(self) -> Digest:
        return self.exe.digest


class CountLinesOfCodeOptions(GoalSubsystem):
    """Count lines of code."""

    name = "cloc"

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--ignored",
            type=bool,
            fingerprint=True,
            help="Show information about files ignored by cloc.",
        )


class CountLinesOfCode(Goal):
    subsystem_cls = CountLinesOfCodeOptions


@goal_rule
async def run_cloc(
    console: Console,
    options: CountLinesOfCodeOptions,
    cloc_binary: ClocBinary,
    sources_snapshots: SourcesSnapshots,
) -> CountLinesOfCode:
    """Runs the cloc Perl script."""
    all_file_names = sorted(
        set(itertools.chain.from_iterable(snapshot.files for snapshot in sources_snapshots))
    )
    file_content = "\n".join(all_file_names).encode()

    if not file_content:
        return CountLinesOfCode(exit_code=0)

    input_files_filename = "input_files.txt"
    input_file_digest = await Get(
        Digest, CreateDigest([FileContent(input_files_filename, file_content)])
    )
    downloaded_cloc_binary = await Get(
        DownloadedExternalTool, ExternalToolRequest, cloc_binary.get_request(Platform.current)
    )
    digest = await Get(
        Digest,
        MergeDigests(
            (
                input_file_digest,
                downloaded_cloc_binary.digest,
                *(snapshot.digest for snapshot in sources_snapshots),
            )
        ),
    )

    report_filename = "report.txt"
    ignore_filename = "ignored.txt"

    cmd = (
        "/usr/bin/perl",
        downloaded_cloc_binary.exe,
        "--skip-uniqueness",  # Skip the file uniqueness check.
        f"--ignored={ignore_filename}",  # Write the names and reasons of ignored files to this file.
        f"--report-file={report_filename}",  # Write the output to this file rather than stdout.
        f"--list-file={input_files_filename}",  # Read an exhaustive list of files to process from this file.
    )
    req = Process(
        argv=cmd,
        input_digest=digest,
        output_files=(report_filename, ignore_filename),
        description=f"Count lines of code for {pluralize(len(all_file_names), 'file')}",
    )
    exec_result = await Get(ProcessResult, Process, req)

    report_digest_contents = await Get(DigestContents, Digest, exec_result.output_digest)
    reports = {
        file_content.path: file_content.content.decode() for file_content in report_digest_contents
    }

    for line in reports[report_filename].splitlines():
        console.print_stdout(line)

    if options.values.ignored:
        console.print_stderr("\nIgnored the following files:")
        for line in reports[ignore_filename].splitlines():
            console.print_stderr(line)

    return CountLinesOfCode(exit_code=0)


def rules():
    return [
        run_cloc,
        SubsystemRule(ClocBinary),
    ]
