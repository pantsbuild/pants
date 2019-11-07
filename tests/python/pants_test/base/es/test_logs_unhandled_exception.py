# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import signal
import time
from contextlib import contextmanager
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.base.exception_sink import ExceptionSink
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import read_file, safe_file_dump, safe_mkdir, touch
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ExceptionSinkIntegrationTest(PantsRunIntegrationTest):

  def _assert_unhandled_exception_log_matches(self, pid, file_contents):
    self.assertRegex(file_contents, """\
timestamp: ([^\n]+)
process title: ([^\n]+)
sys\\.argv: ([^\n]+)
pid: {pid}
Exception caught: \\([^)]*\\)
(.|\n)*

Exception message:.* 1 Exception encountered:
  ResolveError: "this-target-does-not-exist" was not found in namespace ""\\. Did you mean one of:
""".format(pid=pid))
    # Ensure we write all output such as stderr and reporting files before closing any streams.
    self.assertNotIn(
      'Exception message: I/O operation on closed file.',
      file_contents)

  def _get_log_file_paths(self, workdir, pants_run):
    pid_specific_log_file = ExceptionSink.exceptions_log_path(for_pid=pants_run.pid, in_dir=workdir)
    self.assertTrue(os.path.isfile(pid_specific_log_file))

    shared_log_file = ExceptionSink.exceptions_log_path(in_dir=workdir)
    self.assertTrue(os.path.isfile(shared_log_file))

    self.assertNotEqual(pid_specific_log_file, shared_log_file)

    return (pid_specific_log_file, shared_log_file)

  def test_logs_unhandled_exception(self):
    with temporary_dir() as tmpdir:
      pants_run = self.run_pants_with_workdir(
        ['--no-enable-pantsd', 'list', '//:this-target-does-not-exist'],
        workdir=tmpdir,
        # The backtrace should be omitted when --print-exception-stacktrace=False.
        print_exception_stacktrace=False)
      self.assert_failure(pants_run)
      self.assertRegex(pants_run.stderr_data, """\
ERROR: "this-target-does-not-exist" was not found in namespace ""\\. Did you mean one of:
""")
      pid_specific_log_file, shared_log_file = self._get_log_file_paths(tmpdir, pants_run)
      self._assert_unhandled_exception_log_matches(
        pants_run.pid, read_file(pid_specific_log_file))
      self._assert_unhandled_exception_log_matches(
        pants_run.pid, read_file(shared_log_file))
