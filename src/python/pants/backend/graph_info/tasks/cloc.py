# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.graph_info.subsystems.cloc_binary import ClocBinary
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.engine.fs import FilesContent, PathGlobs, PathGlobsAndRoot, Snapshot
from pants.engine.isolated_process import ExecuteProcessRequest
from pants.task.console_task import ConsoleTask
from pants.util.contextutil import temporary_dir


class CountLinesOfCode(ConsoleTask):
  """Print counts of lines of code."""

  @classmethod
  def subsystem_dependencies(cls):
    return super(CountLinesOfCode, cls).subsystem_dependencies() + (ClocBinary,)

  @classmethod
  def register_options(cls, register):
    super(CountLinesOfCode, cls).register_options(register)
    register('--transitive', type=bool, fingerprint=True, default=True,
             help='Operate on the transitive dependencies of the specified targets.  '
                  'Unset to operate only on the specified targets.')
    register('--ignored', type=bool, fingerprint=True,
             help='Show information about files ignored by cloc.')

  def console_output(self, targets):
    if not self.get_options().transitive:
      targets = self.context.target_roots

    # TODO: Work out a nice library-like utility for writing an argfile, as this will be common.
    with temporary_dir() as tmpdir:
      list_file = os.path.join(tmpdir, 'input_files_list')
      input_files = set()
      with open(list_file, 'w') as list_file_out:
        for target in targets:
          for source in target.sources_relative_to_buildroot():
            input_files.add(source)
            list_file_out.write(source)
            list_file_out.write(b'\n')
      list_file_snapshot = self.context._scheduler.capture_snapshots((
        PathGlobsAndRoot(
          PathGlobs(('input_files_list',)),
          str(tmpdir),
        ),
      ))[0]

    cloc_path, cloc_snapshot = ClocBinary.global_instance().hackily_snapshot(self.context)

    # TODO: This should use an input file snapshot which should be provided on the Target object,
    # rather than hackily re-snapshotting each of the input files.
    # See https://github.com/pantsbuild/pants/issues/5762
    input_pathglobs = PathGlobs(tuple(input_files))
    input_snapshot = self.context._scheduler.product_request(Snapshot, [input_pathglobs])[0]

    directory_digest = self.context._scheduler.merge_directories((
      cloc_snapshot.directory_digest,
      input_snapshot.directory_digest,
      list_file_snapshot.directory_digest,
    ))

    cmd = (
      '/usr/bin/perl',
      cloc_path,
      '--skip-uniqueness',
      '--ignored=ignored',
      '--list-file=input_files_list',
      '--report-file=report',
    )

    # The cloc script reaches into $PATH to look up perl. Let's assume it's in /usr/bin.
    req = ExecuteProcessRequest(
      cmd,
      (),
      directory_digest,
      ('ignored', 'report'),
      (),
      15 * 60,
      'cloc'
    )
    exec_result = self.context.execute_process_synchronously(req, 'cloc', (WorkUnitLabel.TOOL,))

    # TODO: Remove this check when https://github.com/pantsbuild/pants/issues/5719 is resolved.
    if exec_result.exit_code != 0:
      raise TaskError('{} ... exited non-zero ({}).'.format(' '.join(cmd), exec_result.exit_code))

    files_content_tuple = self.context._scheduler.product_request(
      FilesContent,
      [exec_result.output_directory_digest]
    )[0].dependencies

    files_content = {fc.path: fc.content for fc in files_content_tuple}
    for line in files_content['report'].split('\n'):
      yield line

    if self.get_options().ignored:
      yield 'Ignored the following files:'
      for line in files_content['ignored'].split('\n'):
        yield line
