# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Set

from pants.base.specs import Specs
from pants.engine.console import Console
from pants.engine.fs import (
  Digest,
  DirectoriesToMerge,
  FileContent,
  FilesContent,
  InputFilesContent,
  Snapshot,
  UrlToFetch,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.legacy.graph import HydratedTargets, TransitiveHydratedTargets
from pants.engine.rules import console_rule, rule
from pants.engine.selectors import Get


@dataclass(frozen=True)
class DownloadedClocScript:
  """Cloc script as downloaded from the pantsbuild binaries repo."""
  script_path: str
  digest: Digest


#TODO(#7790) - We can't call this feature-complete with the v1 version of cloc
# until we have a way to download the cloc binary without hardcoding it
@rule
async def download_cloc_script() -> DownloadedClocScript:
  url = "https://binaries.pantsbuild.org/bin/cloc/1.80/cloc"
  sha_256 = "2b23012b1c3c53bd6b9dd43cd6aa75715eed4feb2cb6db56ac3fbbd2dffeac9d"
  digest = Digest(sha_256, 546279)
  snapshot = await Get[Snapshot](UrlToFetch(url, digest))
  return DownloadedClocScript(script_path=snapshot.files[0], digest=snapshot.directory_digest)


class CountLinesOfCodeOptions(GoalSubsystem):
  name = 'cloc2'

  @classmethod
  def register_options(cls, register) -> None:
    super().register_options(register)
    register('--transitive', type=bool, fingerprint=True, default=True,
             help='Operate on the transitive dependencies of the specified targets.  '
                  'Unset to operate only on the specified targets.')
    register('--ignored', type=bool, fingerprint=True,
             help='Show information about files ignored by cloc.')


class CountLinesOfCode(Goal):
  subsystem_cls = CountLinesOfCodeOptions


@console_rule
async def run_cloc(
  console: Console, options: CountLinesOfCodeOptions, cloc_script: DownloadedClocScript, specs: Specs
) -> CountLinesOfCode:
  """Runs the cloc perl script in an isolated process"""

  transitive = options.values.transitive
  ignored = options.values.ignored

  if transitive:
    transitive_hydrated_targets = await Get[TransitiveHydratedTargets](Specs, specs)
    all_target_adaptors = {ht.adaptor for ht in transitive_hydrated_targets.closure}
  else:
    hydrated_targets = await Get[HydratedTargets](Specs, specs)
    all_target_adaptors = {ht.adaptor for ht in hydrated_targets}

  digests_to_merge = []

  source_paths: Set[str] = set()
  for t in all_target_adaptors:
    sources = getattr(t, 'sources', None)
    if sources is not None:
      digests_to_merge.append(sources.snapshot.directory_digest)
      for f in sources.snapshot.files:
        source_paths.add(str(f))

  file_content = '\n'.join(sorted(source_paths)).encode()

  input_files_filename = 'input_files.txt'
  report_filename = 'report.txt'
  ignore_filename = 'ignored.txt'

  input_file_list = InputFilesContent(FilesContent((FileContent(path=input_files_filename, content=file_content, is_executable=False),)))
  input_file_digest = await Get[Digest](InputFilesContent, input_file_list)
  cloc_script_digest = cloc_script.digest
  digests_to_merge.extend([cloc_script_digest, input_file_digest])
  digest = await Get[Digest](DirectoriesToMerge(directories=tuple(digests_to_merge)))

  cmd = (
    '/usr/bin/perl',
    cloc_script.script_path,
    '--skip-uniqueness', # Skip the file uniqueness check.
    f'--ignored={ignore_filename}', # Write the names and reasons of ignored files to this file.
    f'--report-file={report_filename}', # Write the output to this file rather than stdout.
    f'--list-file={input_files_filename}', # Read an exhaustive list of files to process from this file.
  )

  req = ExecuteProcessRequest(
    argv=cmd,
    input_files=digest,
    output_files=(report_filename, ignore_filename),
    description='cloc',
  )

  exec_result = await Get[ExecuteProcessResult](ExecuteProcessRequest, req)
  files_content = await Get[FilesContent](Digest, exec_result.output_directory_digest)

  file_outputs = {fc.path: fc.content.decode() for fc in files_content.dependencies}

  output = file_outputs[report_filename]

  for line in output.splitlines():
    console.print_stdout(line)

  if ignored:
    console.print_stdout("\nIgnored the following files:")
    ignored = file_outputs[ignore_filename]
    for line in ignored.splitlines():
      console.print_stdout(line)

  return CountLinesOfCode(exit_code=0)


def rules():
  return [
      run_cloc,
      download_cloc_script,
    ]
