# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from dataclasses import dataclass

from pants.backend.graph_info.subsystems.cloc_binary import ClocBinary
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.engine.console import Console
from pants.engine.fs import (
    Digest,
    FileContent,
    FilesContent,
    InputFilesContent,
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
        set(
            itertools.chain.from_iterable(
                sources_snapshot.snapshot.files for sources_snapshot in sources_snapshots
            )
        )
    )
    file_content = "\n".join(all_file_names).encode()

    if not file_content:
        return CountLinesOfCode(exit_code=0)

    input_files_filename = "input_files.txt"
    input_file_digest = await Get[Digest](
        InputFilesContent([FileContent(path=input_files_filename, content=file_content)]),
    )
    downloaded_cloc_binary = await Get[DownloadedExternalTool](
        ExternalToolRequest, cloc_binary.get_request(Platform.current)
    )
    digest = await Get[Digest](
        MergeDigests(
            (
                input_file_digest,
                downloaded_cloc_binary.digest,
                *(sources_snapshot.snapshot.digest for sources_snapshot in sources_snapshots),
            )
        )
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

    exec_result = await Get[ProcessResult](Process, req)
    files_content = await Get[FilesContent](Digest, exec_result.output_digest)

    file_outputs = {fc.path: fc.content.decode() for fc in files_content}

    for line in file_outputs[report_filename].splitlines():
        console.print_stdout(line)

    if options.values.ignored:
        console.print_stderr("\nIgnored the following files:")
        for line in file_outputs[ignore_filename].splitlines():
            console.print_stderr(line)

    return CountLinesOfCode(exit_code=0)


def rules():
    return [
        run_cloc,
        SubsystemRule(ClocBinary),
    ]
