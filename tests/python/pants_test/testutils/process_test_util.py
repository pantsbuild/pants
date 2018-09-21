# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from contextlib import contextmanager

import psutil

from pants.util.objects import datatype


class ProcessStillRunning(AssertionError):
  """Raised when a process shouldn't be running but is."""


def _safe_iter_matching_processes(name):
  for proc in psutil.process_iter():
    try:
      if name in ''.join(proc.cmdline()):
        yield proc
    except (psutil.NoSuchProcess, psutil.AccessDenied):
      pass


def _make_process_table(processes):
  line_tmpl = '{0:>7} {1:>7} {2}'
  proc_tuples = [(p.pid, p.ppid(), ''.join(p.cmdline())) for p in processes]
  return '\n'.join(
    [
      line_tmpl.format('PID', 'PGID', 'CMDLINE')
    ] + [
      line_tmpl.format(*t) for t in sorted(proc_tuples)
    ]
  )


@contextmanager
def no_lingering_process_by_command(name):
  """Asserts that no process exists for a given command with a helpful error, excluding
  existing processes outside of the scope of the contextmanager."""
  context = TrackedProcessesContext(name, set(_safe_iter_matching_processes(name)))
  yield context
  delta_processes = context.current_processes
  if delta_processes:
    raise ProcessStillRunning(
      '{} {} processes lingered after tests:\n{}'
      .format(len(delta_processes), name, _make_process_table(delta_processes))
    )


class TrackedProcessesContext(datatype(['name', 'before_processes'])):
  def current_processes(self):
    """Returns the current set of matching processes created since the context was entered."""
    after_processes = set(_safe_iter_matching_processes(self.name))
    return after_processes.difference(self.before_processes)
