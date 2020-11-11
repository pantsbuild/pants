# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import threading
import time

from pants.util.logging import LogLevel


class ReportingError(Exception):
    pass


class EmitterThread(threading.Thread):
    """Periodically flush the report buffers.

    This thread wakes up periodically and flushes the reporting buffers from memory to make sure
    that the output of long running workunits can be monitored.
    """

    def __init__(self, report, name):
        super().__init__(name=name)
        self._report = report
        # N.B. We must not use the name `self._stop`, as it is already used by Threading.thread
        # and overriding it results in `TypeError: 'Event' object is not callable` when ran with Py3.
        # See https://stackoverflow.com/questions/27102881/python-threading-self-stop-event-object-is-not-callable
        self._stopper = threading.Event()
        self.daemon = True

    def run(self):
        # NB(Eric Ayers) Using self._stopper.wait(timeout=0.5) causes spurious exceptions on shutdown
        # on some platforms. See https://github.com/pantsbuild/pants/issues/2750
        while not self._stopper.is_set():
            self._report.flush()
            time.sleep(0.5)

    def stop_thread(self):
        self._stopper.set()


class Report:
    """A report of a pants run."""

    # Log levels.
    ERROR = 1
    WARN = 2
    INFO = 3
    DEBUG = 4

    _log_level_name_map = {
        LogLevel.ERROR: ERROR,
        LogLevel.WARN: WARN,
        LogLevel.INFO: INFO,
        LogLevel.DEBUG: DEBUG,
    }

    @classmethod
    def report_level_from_log_level(cls, log_level: LogLevel) -> int:
        return cls._log_level_name_map.get(log_level, Report.INFO)

    def __init__(self):
        # We periodically emit newly gathered output from tool invocations.
        self._emitter_thread = EmitterThread(report=self, name="output-emitter")

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

        Each element of msg_elements is either a message or a (message, detail) pair, i.e. of type
        Union[str, bytes, Tuple[str, str]].
        """
        # TODO(6742): Once we have enough MyPy coverage, we can rely on MyPy to catch any issues for us,
        # rather than this runtime check.
        # TODO(6071): No longer allow bytes once Py2 is removed.
        assert all(isinstance(element, (str, bytes, tuple)) for element in msg_elements), (
            "At least one logged message element is not of type "
            "Union[str, bytes, Tuple[str, str]]:\n {}".format(msg_elements)
        )
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
        self._emitter_thread.stop_thread()
        with self._lock:
            self._notify()  # One final time.
            for reporter in self._reporters.values():
                reporter.close()

    def _notify(self):
        # Notify for output in all workunits. Note that output may be coming in from workunits other
        # than the current one, if work is happening in parallel.
        # Assumes self._lock is held by the caller.
        for workunit in self._workunits.values():
            # N.B. Wrap .items() call with list() due to issues with workunit.outputs()
            # changing its size during iteration, which causes an error in Python 3.
            # We did not catch this issue in Python 2, because .items() returns a new list
            # in Python 2. It is not clear why the dictionary size is changing, and this may
            # be a potential source of issues.
            for label, output in list(workunit.outputs().items()):
                s = output.read().decode()
                if len(s) > 0:
                    for reporter in self._reporters.values():
                        reporter.handle_output(workunit, label, s)
