# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
import signal
import time

from pants.base.exception_sink import ExceptionSink, GetLogLocationRequest
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import read_file, safe_mkdir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ExceptionSinkIntegrationTest(PantsRunIntegrationTest):

  @classmethod
  def hermetic(cls):
    return True

  def _assert_unhandled_exception_log_matches(self, pid, file_contents):
    # TODO: ensure there's only one log entry in this file so we can avoid more complicated checks!
    # Search for the log header entry.
    self.assertRegexpMatches(file_contents, """\
timestamp: ([^\n]+)
args: ([^\n]+)
pid: {pid}
""".format(pid=pid))

    # Search for the exception message and the beginning of the stack trace with a hacky regexp.
    expected_error_regexp = re.compile(
      re.escape(
        "Exception caught: (<class 'pants.build_graph.address_lookup_error.AddressLookupError'>)") +
      '\n  File ".*", line [0-9]+, in <module>' +
      '\n    main()')
    self.assertIsNotNone(expected_error_regexp.search(file_contents))

    # Search for the formatted exception message at the end of the log.
    self.assertIn("""\
    \'Build graph construction failed: {} {}\'.format(type(e).__name__, str(e))

Exception message: Build graph construction failed: ExecutionError 1 Exception encountered:
  ResolveError: "this-target-does-not-exist" was not found in namespace "". Did you mean one of:
""", file_contents)

  def _get_log_file_paths(self, workdir, pants_run):
    pid_specific_log_file = ExceptionSink.exceptions_log_path(
      GetLogLocationRequest(pid=pants_run.pid, log_dir=workdir))
    self.assertTrue(os.path.isfile(pid_specific_log_file))

    shared_log_file = ExceptionSink.exceptions_log_path(
      GetLogLocationRequest(log_dir=workdir))
    self.assertTrue(os.path.isfile(shared_log_file))

    self.assertNotEqual(pid_specific_log_file, shared_log_file)

    return (pid_specific_log_file, shared_log_file)

  def test_logs_unhandled_exception(self):
    with temporary_dir() as tmpdir:
      pants_run = self.run_pants_with_workdir([
        # The backtrace should be omitted when printed to stderr, but not when logged.
        '--no-print-exception-stacktrace',
        'list',
        '//:this-target-does-not-exist',
      ], workdir=tmpdir)
      self.assert_failure(pants_run)
      self.assertIn('\n(backtrace omitted)\n', pants_run.stderr_data)
      self.assertIn(' ResolveError: "this-target-does-not-exist" was not found in namespace "". Did you mean one of:',
                    pants_run.stderr_data)

      pid_specific_log_file, shared_log_file = self._get_log_file_paths(tmpdir, pants_run)
      self._assert_unhandled_exception_log_matches(pants_run.pid, read_file(pid_specific_log_file))
      self._assert_unhandled_exception_log_matches(pants_run.pid, read_file(shared_log_file))

  def _assert_graceful_signal_log_matches(self, pid, signum, contents):
    self.assertRegexpMatches(contents, """\
timestamp: ([^\n]+)
args: ([^\n]+)
pid: {pid}
Signal {signum} was raised\\. Exiting with failure\\.
\\(backtrace omitted\\)
""".format(pid=pid, signum=signum))

  def test_dumps_traceback_on_fatal_signal(self):
    with temporary_dir() as tmpdir:
      # The path is required to end in '.pants.d'. This is validated in
      # GoalRunner#is_valid_workdir().
      workdir = os.path.join(tmpdir, '.pants.d')
      safe_mkdir(workdir)
      file_to_make = os.path.join(tmpdir, 'some_file')
      waiter_handle = self.run_pants_with_workdir_without_waiting([
        '--no-enable-pantsd',
        'run', 'testprojects/src/python/coordinated_runs:waiter',
        '--', file_to_make,
      ], workdir)
      time.sleep(5)
      # TODO: need to test at least SIGABRT or one of the other signals faulthandler is covering as
      # well (which only have a backtrace)!
      # Send a SIGTERM to the local pants process.
      waiter_handle.process.terminate()
      waiter_run = waiter_handle.join()
      self.assert_failure(waiter_run)

      pid_specific_log_file, shared_log_file = self._get_log_file_paths(workdir, waiter_run)
      self.assertRegexpMatches(waiter_run.stderr_data, re.escape("""\
Signal {signum} was raised. Exiting with failure.
(backtrace omitted)
""".format(signum=signal.SIGTERM)))
      # TODO: the methods below are wrong for this signal error log (as opposed to an uncaught
      # exception), but also, the log file is empty for some reason. Solving this should solve the
      # xfailed test.
      self._assert_graceful_signal_log_matches(
        waiter_run.pid, signal.SIGTERM, read_file(pid_specific_log_file))
      self._assert_graceful_signal_log_matches(
        waiter_run.pid, signal.SIGTERM, read_file(shared_log_file))

  def test_reset_exiter(self):
    """???"""

  def test_reset_interactive_output_stream(self):
    """???"""
