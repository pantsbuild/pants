# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.binaries.binary_util import BinaryUtil
from pants.util.contextutil import temporary_dir


class CountLinesOfCode(ConsoleTask):
  """Counts lines of code."""

  @classmethod
  def global_subsystems(cls):
    return super(CountLinesOfCode, cls).global_subsystems() + (BinaryUtil.Factory,)

  @classmethod
  def register_options(cls, register):
    super(CountLinesOfCode, cls).register_options(register)
    register('--version', advanced=True, fingerprint=True, default='1.64', help='Version of cloc.')
    register('--ignored', action='store_true', fingerprint=True,
             help='Show information about files ignored by cloc.')

  def _get_cloc_script(self):
    binary_util = BinaryUtil.Factory.create()
    return binary_util.select_script('scripts/cloc', self.get_options().version, 'cloc')

  def console_output(self, targets):
    # TODO(benjy): artifact caching?  That would make things more complicated, e.g., to cache
    # per-target counts we'd have to capture the raw data from cloc and then do extra aggregation
    # to display results.  We'd also have to consider invalidation, which means we'd have separate
    # computing the counts from displaying them (as we'll always want to print results for all
    # targets, not just the invalidated ones). In fact this is true for several ConsoleTasks,
    # as is the question of how to capture their output and display it in the HTML report.
    # Something to look into more generally, after the new engine lands, when we've completely
    # regularized task inputs/outputs, and eliminated side effects other than
    # "writing to the console", which we'll presumably create special support for.
    buildroot = get_buildroot()
    with temporary_dir() as tmpdir:
      # Write the paths of all files we want cloc to process to the so-called 'list file'.
      list_file = os.path.join(tmpdir, 'list_file')
      with open(list_file, 'w') as list_file_out:
        for target in targets:
          for source in target.sources_relative_to_buildroot():
            list_file_out.write(os.path.join(buildroot, source))
            list_file_out.write(b'\n')

      report_file = os.path.join(tmpdir, 'report_file')
      ignored_file = os.path.join(tmpdir, 'ignored')
      cloc_script = self._get_cloc_script()
      cmd = [cloc_script,
             '--skip-uniqueness',
             '--ignored={}'.format(ignored_file),
             '--list-file={}'.format(list_file),
             '--report-file={}'.format(report_file)]
      with self.context.new_workunit(name='cloc',
                                     labels=[WorkUnitLabel.TOOL],
                                     cmd=' '.join(cmd)) as workunit:
        result = subprocess.call(cmd,
                                 stdout=workunit.output('stdout'),
                                 stderr=workunit.output('stderr'))

      if result != 0:
        raise TaskError('{} ... exited non-zero ({}).'.format(' '.join(cmd), result))

      ret = []
      with open(report_file, 'r') as report_file_in:
        ret.extend(report_file_in.read().split('\n'))

      if self.get_options().ignored:
        ret.append('Ignored the following files:')
        with open(ignored_file, 'r') as ignored_file_in:
          ret.extend(ignored_file_in.read().split('\n'))

      return ret
