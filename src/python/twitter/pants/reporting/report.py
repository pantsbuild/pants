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

  def update_settings(self, updates_map):
    """Modify reporting settings once we've got cmd-line flags etc.

       updates_map - a map from reporter name to a k-v dict of updates.
    """
    for name, updates in updates_map.items():
      if name in self._reporters:
        self._reporters[name].update_settings(updates)

  def open(self):
    for reporter in self._reporters.values():
      reporter.open()
    self._emitter_thread.start()

  def add_reporter(self, name, reporter):
    self._reporters[name] = reporter

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
    for workunit in self._workunits.values():
      for label, output in workunit.outputs().items():
        s = output.read()
        if len(s) > 0:
          for reporter in self._reporters.values():
            reporter.handle_output(workunit, label, s)
