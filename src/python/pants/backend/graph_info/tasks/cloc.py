# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import open

from future.utils import text_type

from pants.backend.graph_info.subsystems.cloc_binary import ClocBinary
from pants.base.workunit import WorkUnitLabel
from pants.engine.fs import FilesContent, PathGlobs, PathGlobsAndRoot
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

    input_snapshots = tuple(
      target.sources_snapshot(scheduler=self.context._scheduler) for target in targets
    )
    input_files = {f.path for snapshot in input_snapshots for f in snapshot.files}

    # TODO: Work out a nice library-like utility for writing an argfile, as this will be common.
    with temporary_dir() as tmpdir:
      list_file = os.path.join(tmpdir, 'input_files_list')
      with open(list_file, 'w') as list_file_out:
        for input_file in sorted(input_files):
          list_file_out.write(input_file)
          list_file_out.write('\n')
      list_file_snapshot = self.context._scheduler.capture_snapshots((
        PathGlobsAndRoot(
          PathGlobs(('input_files_list',)),
          text_type(tmpdir),
        ),
      ))[0]

    cloc_path, cloc_snapshot = ClocBinary.global_instance().hackily_snapshot(self.context)

    directory_digest = self.context._scheduler.merge_directories(tuple(s.directory_digest for s in
      input_snapshots + (
      cloc_snapshot,
      list_file_snapshot,
    )))

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
      argv=cmd,
      input_files=directory_digest,
      output_files=('ignored', 'report'),
      description='cloc',
    )
    exec_result = self.context.execute_process_synchronously_without_raising(req, 'cloc', (WorkUnitLabel.TOOL,))

    files_content_tuple = self.context._scheduler.product_request(
      FilesContent,
      [exec_result.output_directory_digest]
    )[0].dependencies

    files_content = {fc.path: fc.content.decode('utf-8') for fc in files_content_tuple}
    for line in files_content['report'].split('\n'):
      yield line

    if self.get_options().ignored:
      yield 'Ignored the following files:'
      for line in files_content['ignored'].split('\n'):
        yield line
