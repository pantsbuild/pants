# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from contextlib import contextmanager

import psutil


class ProcessStillRunning(AssertionError):
  """Raised when a process shouldn't be running but is."""


def _safe_iter_matching_processes(name):
  for proc in psutil.process_iter():
    try:
      if name in ''.join(proc.cmdline()):
        yield proc
    except (psutil.NoSuchProcess, psutil.AccessDenied):
      pass


def _matching_process_set(name):
  return {p for p in _safe_iter_matching_processes(name)}


@contextmanager
def no_lingering_process_by_command(name):
  """Asserts that no process exists for a given command with a helpful error, excluding
  existing processes outside of the scope of the contextmanager."""
  existing_processes = _matching_process_set(name)
  yield
  delta_processes = existing_processes.difference(_matching_process_set(name))
  if delta_processes:
    pids = [p.pid for p in delta_processes]
    cmdlines = [''.join(p.cmdline()) for p in delta_processes]
    raise ProcessStillRunning(
      '{} {} processes were detected at PIDS {} (cmdlines={})'
      .format(len(delta_processes), name, pids, cmdlines)
    )
