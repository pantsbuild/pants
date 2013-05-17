import threading

from twitter.common.threading import PeriodicThread


class ReportingError(Exception):
  pass

class Report(object):
  """A report of a pants run."""

  def __init__(self):
    # We periodically emit newly gathered output from tool invocations.
    self._emitter_thread = \
      PeriodicThread(target=self.flush, name='output-emitter', period_secs=0.5)
    self._emitter_thread.daemon = True

    # Map from workunit id to workunit.
    self._workunits = {}

    # We report to these reporters.
    self._reporters = []

    # We synchronize on this, to support parallel execution.
    self._lock = threading.Lock()

  def open(self):
    for reporter in self._reporters:
      reporter.open()
    self._emitter_thread.start()

  def add_reporter(self, reporter):
    self._reporters.append(reporter)

  def start_workunit(self, workunit):
    with self._lock:
      self._workunits[workunit.id] = workunit
      for reporter in self._reporters:
        reporter.start_workunit(workunit)

  def message(self, workunit, *msg_elements):
    """Report a message.

    Each element of msg_elements is either a message string or a (message, detail) pair.
    """
    with self._lock:
      for reporter in self._reporters:
        reporter.handle_message(workunit, *msg_elements)

  def end_workunit(self, workunit):
    with self._lock:
      self._notify()  # Make sure we flush everything reported until now.
      for reporter in self._reporters:
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
      for reporter in self._reporters:
        reporter.close()

  def _notify(self):
    # Notify for output in all workunits. Note that output may be coming in from workunits other
    # than the current one, if work is happening in parallel.
    for workunit in self._workunits.values():
      for label, output in workunit.outputs().items():
        s = output.read()
        if len(s) > 0:
          for reporter in self._reporters:
            reporter.handle_output(workunit, label, s)
