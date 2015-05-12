# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import Queue as queue
import thread
import threading
import traceback
from collections import namedtuple


class ReportingError(Exception):
  pass

class ReportWork(namedtuple('ReportWork', ['func', 'args'])):
  def __call__(self):
    self.func(*self.args)

# Seconds to wait for the report thread to close out reports on an error.
REPORT_THREAD_SHUTDOWN_TIMEOUT = 1
# Seconds to wait on the shutdown event before continuing to process report messages
REPORT_THREAD_EVENT_HANDLING_INTERVAL = 0.5

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

    # Synchronizes access to the reporters added to this report.
    self._reporters_lock = threading.Lock()
    # Queues reporting work to be done on the reporting thread.
    self._work_queue = queue.Queue()
    # Communicates shutdown process to report thread.
    self._shutdown_event = threading.Event()
    # We periodically emit newly gathered output from tool invocations.
    self._report_thread = threading.Thread(name='reporting-emit', target=self._reporting_target)
    self._report_thread.daemon = True
    self._reporting_done = False

    # Notifies reporting thread of new workunit output and of reporting shutdown.
    self._watcher_thread = threading.Thread(name='reporting-watcher', target=self._watcher_target)
    self._watcher_thread.daemon = True
    # Map from workunit id to workunit.
    self._workunits = {}

    # We report to these reporters.
    self._reporters = {}  # name -> Reporter instance.

  # Note that if you add/remove reporters after open() has been called you have
  # to ensure that their state is set up correctly. Best only to do this with
  # stateless reporters, such as PlainTextReporter.

  def add_reporter(self, name, reporter):
    with self._reporters_lock:
      self._reporters[name] = reporter

  def remove_reporter(self, name):
    with self._reporters_lock:
      ret = self._reporters[name]
      del self._reporters[name]
      return ret

  def _reporter_list(self):
    with self._reporters_lock:
      return self._reporters.values()

  def open(self):
    self._report_thread.start()
    self._watcher_thread.start()

  def start_workunit(self, workunit):
    self._submit_work(self._start_workunit, (workunit,))

  def log(self, workunit, level, *msg_elements):
    """Log a message.

    Each element of msg_elements is either a message string or a (message, detail) pair.
    """
    self._submit_work(self._handle_log, (workunit, level,) + msg_elements)

  def end_workunit(self, workunit):
    """Report the end of the workunit. Expects to be called before outputs are closed out."""
    self._submit_work(self._end_workunit, (workunit, workunit.unread_outputs_contents()))

  def close(self):
    self._shutdown_event.set()
    self._report_thread.join(timeout=REPORT_THREAD_SHUTDOWN_TIMEOUT)

  def _watcher_target(self):
    try:
      while not self._shutdown_event.wait(REPORT_THREAD_EVENT_HANDLING_INTERVAL):
        self._submit_work(self._handle_output_for_all_workunits, ())
    except KeyboardInterrupt:
      thread.interrupt_main()
      raise
    finally:
      self._submit_work(self._mark_as_done, ())

  def _reporting_target(self):
    try:
      for reporter in self._reporter_list():
        reporter.open()

      while not self._reporting_done:
        try:
          work = self._work_queue.get(timeout=REPORT_THREAD_EVENT_HANDLING_INTERVAL)
        except queue.Empty:
          continue
        work()

    except KeyboardInterrupt:
      thread.interrupt_main()
      raise
    except Exception:
      # TODO: add mechanism to notify goal runner that the interrupt triggered here was not caused
      # by user action
      traceback.print_exc()
      thread.interrupt_main()
      raise
    finally:
      # Wait until main thread triggers shutdown to ensure all in progress workunits have submitted
      # their output.
      self._shutdown_event.wait()

      self._handle_output_for_all_workunits() # One final time.
      remaining_work = self._drain_work_queue()
      for work in remaining_work:
        work()

      for reporter in self._reporter_list():
        reporter.close()

  def _start_workunit(self, workunit):
    self._workunits[workunit.id] = workunit
    for reporter in self._reporter_list():
      reporter.start_workunit(workunit)

  def _handle_log(self, workunit, level, *msg_elements):
    for reporter in self._reporter_list():
      reporter.handle_log(workunit, level, *msg_elements)

  def _end_workunit(self, workunit, remaing_unread_output):
    self._handle_outputs(workunit, remaing_unread_output)
    for reporter in self._reporter_list():
      reporter.end_workunit(workunit)

    if workunit.id in self._workunits:
      del self._workunits[workunit.id]

  def _handle_outputs(self, workunit, outputs):
    for label, s in outputs.items():
      if len(s) > 0:
        for reporter in self._reporter_list():
          reporter.handle_output(workunit, label, s)

  def _handle_output_for_all_workunits(self):
    # Notify for output in all workunits. Note that output may be coming in from workunits other
    # than the current one, if work is happening in parallel.
    for workunit in self._workunits.values():
      self._handle_outputs(workunit, workunit.unread_outputs_contents())

  def _mark_as_done(self):
    self._reporting_done = True

  def _drain_work_queue(self):
    # Drains the queue without blocking
    ret = []
    while not self._work_queue.empty():
      try:
        ret.append(self._work_queue.get_nowait())
      except queue.Empty:
        break
    return ret

  def _submit_work(self, func, args):
    self._work_queue.put(ReportWork(func, args))
