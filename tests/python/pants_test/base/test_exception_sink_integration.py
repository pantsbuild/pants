# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import re

from pants.base.exception_sink import ExceptionSink, LogLocation
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import read_file
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ExceptionSinkIntegrationTest(PantsRunIntegrationTest):

  def _assert_log_matches(self, pid, file_contents):
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

      # TODO: Check that the exception AND a backtrace are logged to both of these!
      pid_specific_log_file = ExceptionSink.exceptions_log_path(
        LogLocation(log_dir=tmpdir, pid=pants_run.pid))
      self._assert_log_matches(pants_run.pid, read_file(pid_specific_log_file))
      shared_log_file = ExceptionSink.exceptions_log_path(
        LogLocation(log_dir=tmpdir, pid=None))
      self._assert_log_matches(pants_run.pid, read_file(shared_log_file))

  def test_dumps_traceback_on_fatal_signal(self):
    """???"""

  def test_reset_exiter(self):
    """???"""

  def test_reset_interactive_output_stream(self):
    """???"""
