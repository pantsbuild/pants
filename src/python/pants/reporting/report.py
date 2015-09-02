# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import threading

from twitter.common.threading import PeriodicThread


class ReportingError(Exception):
  pass


class Report(object):
  """A report of a pants run."""

  # Log levels.
  FATAL = 0
  ERROR = 1
  WARN = 2
  INFO = 3
  DEBUG = 4

  _log_level_name_map = {
    'FATAL': FATAL, 'ERROR': ERROR, 'WARN': WARN, 'WARNING': WARN, 'INFO': INFO, 'DEBUG': DEBUG
  }

  @staticmethod
  def log_level_from_string(s):
    s = s.upper()
    return Report._log_level_name_map.get(s, Report.INFO)

  def __init__(self):
    # We periodically emit newly gathered output from tool invocations.
    self._emitter_thread = \
      PeriodicThread(target=self.flush, name='output-emitter', period_secs=0.5)
    self._emitter_thread.daemon = True

    # Map from workunit id to workunit.
    self._workunits = {}

    # We report to these reporters.
    self._reporters = {}  # name -> Reporter instance.

    # We synchronize on this, to support parallel execution.
    self._lock = threading.Lock()

  def open(self):
    with self._lock:
      for reporter in self._reporters.values():
        reporter.open()
    self._emitter_thread.start()

  # Note that if you addr/remove reporters after open() has been called you have
  # to ensure that their state is set up correctly. Best only to do this with
  # stateless reporters, such as ConsoleReporter.
  def add_reporter(self, name, reporter):
    with self._lock:
      self._reporters[name] = reporter

  def remove_reporter(self, name):
    with self._lock:
      ret = self._reporters[name]
      del self._reporters[name]
      return ret

  def start_workunit(self, workunit):
    with self._lock:
      self._workunits[workunit.id] = workunit
      for reporter in self._reporters.values():
        reporter.start_workunit(workunit)

  def log(self, workunit, level, *msg_elements):
    """Log a message.

    Each element of msg_elements is either a message string or a (message, detail) pair.
    """
    with self._lock:
      for reporter in self._reporters.values():
        reporter.handle_log(workunit, level, *msg_elements)

  def end_workunit(self, workunit):
    with self._lock:
      self._notify()  # Make sure we flush everything reported until now.
      for reporter in self._reporters.values():
        reporter.end_workunit(workunit)
      if workunit.id in self._workunits:
        del self._workunits[workunit.id]

  def flush(self):
    with self._lock:
      self._notify()

  def close(self):
    self._emitter_thread.stop()
    with self._lock:
      self._notify()  # One final time.
      for reporter in self._reporters.values():
        reporter.close()

  def _notify(self):
    # Notify for output in all workunits. Note that output may be coming in from workunits other
    # than the current one, if work is happening in parallel.
    # Assumes self._lock is held by the caller.
    for workunit in self._workunits.values():
      for label, output in workunit.outputs().items():
        s = output.read()
        if len(s) > 0:
          for reporter in self._reporters.values():
            reporter.handle_output(workunit, label, s)
