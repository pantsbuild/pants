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


class ReportMessage(namedtuple('ReportMessage', ['type', 'args'])):
  START_WORKUNIT = 0
  END_WORKUNIT = 1
  LOG = 2

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
    # Queues messages to report
    self._message_queue = queue.Queue()
    # Communicates shutdown process to report thread.
    self._shutdown_event = threading.Event()
    # We periodically emit newly gathered output from tool invocations.
    self._report_thread = threading.Thread(name='reporting', target=self._reporting_target)
    self._report_thread.daemon = True

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

  def start_workunit(self, workunit):
    self._message_queue.put(ReportMessage(ReportMessage.START_WORKUNIT, (workunit,)))

  def log(self, workunit, level, *msg_elements):
    """Log a message.

    Each element of msg_elements is either a message string or a (message, detail) pair.
    """
    self._message_queue.put(ReportMessage(ReportMessage.LOG, (workunit, level,) + msg_elements))

  def end_workunit(self, workunit):
    self._message_queue.put(ReportMessage(ReportMessage.END_WORKUNIT, (workunit,)))

  def close(self):
    self._shutdown_event.set()
    self._report_thread.join(timeout=REPORT_THREAD_SHUTDOWN_TIMEOUT)

  def _reporting_target(self):
    try:
      for reporter in self._reporter_list():
        reporter.open()

      while not self._shutdown_event.wait(REPORT_THREAD_EVENT_HANDLING_INTERVAL):
        current_messages = self._drain_message_queue()

        self._handle_report_event(current_messages)

        self._handle_new_workunit_output()
    except KeyboardInterrupt:
      thread.interrupt_main()
      raise
    except Exception:
      traceback.print_exc()
      thread.interrupt_main()
      raise
    finally:
      self._handle_new_workunit_output() # One final time.
      for reporter in self._reporter_list():
        reporter.close()

  def _start_workunit(self, message):
    workunit = message.args[0]
    self._workunits[workunit.id] = workunit
    for reporter in self._reporter_list():
      reporter.start_workunit(*message.args)

  def _handle_log(self, message):
    for reporter in self._reporter_list():
      reporter.handle_log(*message.args)

  def _end_workunit(self, message):
    workunit = message.args[0]
    self._handle_new_workunit_output()
    for reporter in self._reporter_list():
      reporter.end_workunit(*message.args)

    if workunit.id in self._workunits:
      del self._workunits[workunit.id]

  def _drain_message_queue(self):
    # Drains the queue without blocking
    current_messages = []
    while not self._message_queue.empty():
      try:
        current_messages.append(self._message_queue.get_nowait())
      except queue.Empty:
        break
    return current_messages

  def _handle_report_event(self, current_messages):
    for message in current_messages:
      if message.type is ReportMessage.START_WORKUNIT:
        self._start_workunit(message)
      elif message.type is ReportMessage.LOG:
        self._handle_log(message)
      elif message.type is ReportMessage.END_WORKUNIT:
        self._end_workunit(message)
      else:
        raise ReportingError("Unknown message type: {}".format(message))

  def _handle_new_workunit_output(self):
    # Notify for output in all workunits. Note that output may be coming in from workunits other
    # than the current one, if work is happening in parallel.
    for workunit in self._workunits.values():
      for label, s in workunit.unread_outputs_contents().items():
        if len(s) > 0:
          for reporter in self._reporter_list():
            reporter.handle_output(workunit, label, s)
