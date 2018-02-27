# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.graph_info.subsystems.cloc_binary import ClocBinary
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.task.console_task import ConsoleTask
from pants.util.contextutil import temporary_dir
from pants.util.process_handler import subprocess


class CountLinesOfCode(ConsoleTask):
  """Print counts of lines of code."""

  @classmethod
  def subsystem_dependencies(cls):
    return super(CountLinesOfCode, cls).subsystem_dependencies() + (ClocBinary,)

  @classmethod
  def register_options(cls, register):
    super(CountLinesOfCode, cls).register_options(register)
    register('--version', advanced=True, fingerprint=True, default='1.66',
             removal_version='1.7.0.dev0', removal_hint='Use --version in scope cloc-binary',
             help='Version of cloc.')
    register('--transitive', type=bool, fingerprint=True, default=True,
             help='Operate on the transitive dependencies of the specified targets.  '
                  'Unset to operate only on the specified targets.')
    register('--ignored', type=bool, fingerprint=True,
             help='Show information about files ignored by cloc.')

  def _get_cloc_script(self):
    return ClocBinary.global_instance().select(self.context)

  def console_output(self, targets):
    if not self.get_options().transitive:
      targets = self.context.target_roots

    buildroot = get_buildroot()
    with temporary_dir() as tmpdir:
      # Write the paths of all files we want cloc to process to the so-called 'list file'.
      # TODO: 1) list_file, report_file and ignored_file should be relative files within the
      # execution "chroot", 2) list_file should be part of an input files Snapshot, and
      # 3) report_file and ignored_file should be part of an output files Snapshot, when we have
      # that capability.
      list_file = os.path.join(tmpdir, 'list_file')
      with open(list_file, 'w') as list_file_out:
        for target in targets:
          for source in target.sources_relative_to_buildroot():
            list_file_out.write(os.path.join(buildroot, source))
            list_file_out.write(b'\n')

      report_file = os.path.join(tmpdir, 'report_file')
      ignored_file = os.path.join(tmpdir, 'ignored')

      # TODO: Look at how to make BinaryUtil support Snapshots - such as adding an instrinsic to do
      # network fetch directly into a Snapshot.
      # See http://cloc.sourceforge.net/#options for cloc cmd-line options.
      cmd = (
        self._get_cloc_script(),
        '--skip-uniqueness',
        '--ignored={}'.format(ignored_file),
        '--list-file={}'.format(list_file),
        '--report-file={}'.format(report_file)
      )
      with self.context.new_workunit(
        name='cloc',
        labels=[WorkUnitLabel.TOOL],
        cmd=' '.join(cmd)) as workunit:
        exit_code = subprocess.call(
          cmd,
          stdout=workunit.output('stdout'),
          stderr=workunit.output('stderr')
        )

        if exit_code != 0:
          raise TaskError('{} ... exited non-zero ({}).'.format(' '.join(cmd), exit_code))

      with open(report_file, 'r') as report_file_in:
        for line in report_file_in.read().split('\n'):
          yield line

      if self.get_options().ignored:
        yield 'Ignored the following files:'
        with open(ignored_file, 'r') as ignored_file_in:
          for line in ignored_file_in.read().split('\n'):
            yield line
