# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from dataclasses import dataclass

from pants.engine.console import Console
from pants.engine.fs import (
  Digest,
  DirectoriesToMerge,
  FileContent,
  FilesContent,
  InputFilesContent,
  SingleFileExecutable,
  Snapshot,
  UrlToFetch,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.legacy.graph import SourcesSnapshots
from pants.engine.rules import goal_rule, rule
from pants.engine.selectors import Get


@dataclass(frozen=True)
class DownloadedClocScript:
  """Cloc script as downloaded from the pantsbuild binaries repo."""
  exe: SingleFileExecutable

  @property
  def script_path(self) -> str:
    return self.exe.exe_filename

  @property
  def digest(self) -> Digest:
    return self.exe.directory_digest


#TODO(#7790) - We can't call this feature-complete with the v1 version of cloc
# until we have a way to download the cloc binary without hardcoding it
@rule
async def download_cloc_script() -> DownloadedClocScript:
  url = "https://binaries.pantsbuild.org/bin/cloc/1.80/cloc"
  sha_256 = "2b23012b1c3c53bd6b9dd43cd6aa75715eed4feb2cb6db56ac3fbbd2dffeac9d"
  digest = Digest(sha_256, 546279)
  snapshot = await Get[Snapshot](UrlToFetch(url, digest))
  return DownloadedClocScript(SingleFileExecutable(snapshot))


class CountLinesOfCodeOptions(GoalSubsystem):
  """Print counts of lines of code."""
  name = 'cloc2'

  @classmethod
  def register_options(cls, register) -> None:
    super().register_options(register)
    register('--ignored', type=bool, fingerprint=True,
             help='Show information about files ignored by cloc.')


class CountLinesOfCode(Goal):
  subsystem_cls = CountLinesOfCodeOptions


@goal_rule
async def run_cloc(
  console: Console,
  options: CountLinesOfCodeOptions,
  cloc_script: DownloadedClocScript,
  sources_snapshots: SourcesSnapshots,
) -> CountLinesOfCode:
  """Runs the cloc perl script in an isolated process"""

  snapshots = [sources_snapshot.snapshot for sources_snapshot in sources_snapshots]
  file_content = '\n'.join(
    sorted(set(itertools.chain.from_iterable(snapshot.files for snapshot in snapshots)))
  ).encode()

  if not file_content:
    return CountLinesOfCode(exit_code=0)

  input_files_filename = 'input_files.txt'
  input_file_digest = await Get[Digest](
    InputFilesContent([FileContent(path=input_files_filename, content=file_content)]),
  )
  digest = await Get[Digest](
    DirectoriesToMerge(
      (
        input_file_digest,
        cloc_script.digest,
        *(snapshot.directory_digest for snapshot in snapshots),
      )
    )
  )

  report_filename = 'report.txt'
  ignore_filename = 'ignored.txt'

  cmd = (
    '/usr/bin/perl',
    cloc_script.script_path,
    '--skip-uniqueness',  # Skip the file uniqueness check.
    f'--ignored={ignore_filename}',  # Write the names and reasons of ignored files to this file.
    f'--report-file={report_filename}',  # Write the output to this file rather than stdout.
    f'--list-file={input_files_filename}',  # Read an exhaustive list of files to process from this file.
  )
  req = ExecuteProcessRequest(
    argv=cmd,
    input_files=digest,
    output_files=(report_filename, ignore_filename),
    description='cloc',
  )

  exec_result = await Get[ExecuteProcessResult](ExecuteProcessRequest, req)
  files_content = await Get[FilesContent](Digest, exec_result.output_directory_digest)

  file_outputs = {fc.path: fc.content.decode() for fc in files_content}

  for line in file_outputs[report_filename].splitlines():
    console.print_stdout(line)

  if options.values.ignored:
    console.print_stdout("\nIgnored the following files:")
    for line in file_outputs[ignore_filename].splitlines():
      console.print_stdout(line)

  return CountLinesOfCode(exit_code=0)


def rules():
  return [
      run_cloc,
      download_cloc_script,
    ]
