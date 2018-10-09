# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
import signal
import time
from contextlib import contextmanager

from pants.base.build_environment import get_buildroot
from pants.base.exception_sink import ExceptionSink
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import read_file, safe_file_dump, safe_mkdir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ExceptionSinkIntegrationTest(PantsRunIntegrationTest):

  def _assert_unhandled_exception_log_matches(self, pid, nonce, file_contents):
    self.assertRegexpMatches(file_contents, """\
timestamp: ([^\n]+)
process title: ([^\n]+)
sys\\.argv: ([^\n]+)
bootstrap options: OptionValueContainer\\(<with value map = .*build_ignore.*{nonce}.*>\\)
pid: {pid}
Exception caught: \\(<class 'pants\\.build_graph\\.address_lookup_error\\.AddressLookupError'>\\)
  File ".*", line [0-9]+, in <module>
    main\\(\\)
(.|\n)*

Exception message: Build graph construction failed: ExecutionError 1 Exception encountered:
  ResolveError: "this-target-does-not-exist" was not found in namespace ""\\. Did you mean one of:
""".format(pid=pid, nonce=nonce))

  def _get_log_file_paths(self, workdir, pants_run):
    pid_specific_log_file = ExceptionSink.exceptions_log_path(for_pid=pants_run.pid, in_dir=workdir)
    self.assertTrue(os.path.isfile(pid_specific_log_file))

    shared_log_file = ExceptionSink.exceptions_log_path(in_dir=workdir)
    self.assertTrue(os.path.isfile(shared_log_file))

    self.assertNotEqual(pid_specific_log_file, shared_log_file)

    return (pid_specific_log_file, shared_log_file)

  def test_logs_unhandled_exception(self):
    nonce = 'random_string'
    with temporary_dir() as tmpdir:
      pants_run = self.run_pants_with_workdir(
        ['--build-ignore=+["{}"]'.format(nonce), 'list', '//:this-target-does-not-exist'],
        workdir=tmpdir,
        # The backtrace should be omitted when --print-exception-stacktrace=False.
        print_exception_stacktrace=False)
      self.assert_failure(pants_run)
      self.assertRegexpMatches(pants_run.stderr_data, """\\A\
timestamp: ([^\n]+)
Exception caught: \\(<class 'pants\\.build_graph\\.address_lookup_error\\.AddressLookupError'>\\)
\\(backtrace omitted\\)
Exception message: Build graph construction failed: ExecutionError 1 Exception encountered:
  ResolveError: "this-target-does-not-exist" was not found in namespace ""\\. Did you mean one of:
""")

      pid_specific_log_file, shared_log_file = self._get_log_file_paths(tmpdir, pants_run)
      self._assert_unhandled_exception_log_matches(
        pants_run.pid, nonce, read_file(pid_specific_log_file))
      self._assert_unhandled_exception_log_matches(
        pants_run.pid, nonce, read_file(shared_log_file))

  def _assert_graceful_signal_log_matches(self, pid, signum, nonce, contents):
    self.assertRegexpMatches(contents, """\
timestamp: ([^\n]+)
process title: ([^\n]+)
sys\\.argv: ([^\n]+)
bootstrap options: OptionValueContainer\\(<with value map = .*build_ignore.*{nonce}.*>\\)
pid: {pid}
Signal {signum} was raised\\. Exiting with failure\\.
\\(backtrace omitted\\)
""".format(pid=pid, signum=signum, nonce=re.escape(nonce)))

  @contextmanager
  def _make_waiter_handle(self, nonce=None):
    # NB: The `nonce` is a string we ensure is in the bootstrap options for the specific pants
    # subprocess invoked here by adding it to --build-ignore. This way we can ensure the bootstrap
    # options printed in the error message are exactly what we expect.
    nonce = nonce or '<default nonce>'
    with temporary_dir() as tmpdir:
      # The path is required to end in '.pants.d'. This is validated in
      # GoalRunner#is_valid_workdir().
      workdir = os.path.join(tmpdir, '.pants.d')
      safe_mkdir(workdir)
      file_to_make = os.path.join(tmpdir, 'some_file')
      waiter_handle = self.run_pants_with_workdir_without_waiting([
        '--no-enable-pantsd',
        '--build-ignore=+["{}"]'.format(nonce),
        'run', 'testprojects/src/python/coordinated_runs:waiter',
        '--', file_to_make,
      ], workdir)
      yield (workdir, waiter_handle)

  @contextmanager
  def _send_signal_to_waiter_handle(self, signum, nonce=None):
    # This needs to be a contextmanager as well, because workdir may be temporary.
    with self._make_waiter_handle(nonce=nonce) as (workdir, waiter_handle):
      # Wait for the python run to be running.
      time.sleep(5)
      os.kill(waiter_handle.process.pid, signum)
      waiter_run = waiter_handle.join()
      self.assert_failure(waiter_run)
      # Return the (failed) pants execution result.
      yield (workdir, waiter_run)

  def test_dumps_logs_on_terminate(self):
    nonce = 'dumps_logs_random_string'
    # Send a SIGTERM to the local pants process.
    with self._send_signal_to_waiter_handle(signal.SIGTERM, nonce=nonce) as (workdir, waiter_run):
      self.assertRegexpMatches(waiter_run.stderr_data, """\
timestamp: ([^\n]+)
Signal {signum} was raised. Exiting with failure.
\\(backtrace omitted\\)
""".format(signum=signal.SIGTERM))
      # Check that the logs show a graceful exit by SIGTERM.
      pid_specific_log_file, shared_log_file = self._get_log_file_paths(workdir, waiter_run)
      self._assert_graceful_signal_log_matches(
        waiter_run.pid, signal.SIGTERM, nonce, read_file(pid_specific_log_file))
      self._assert_graceful_signal_log_matches(
          waiter_run.pid, signal.SIGTERM, nonce, read_file(shared_log_file))

  def test_dumps_traceback_on_sigabrt(self):
    # SIGABRT sends a traceback to the log file for the current process thanks to
    # faulthandler.enable().
    with self._send_signal_to_waiter_handle(signal.SIGABRT) as (workdir, waiter_run):
      # Check that the logs show an abort signal and the beginning of a traceback.
      pid_specific_log_file, shared_log_file = self._get_log_file_paths(workdir, waiter_run)
      self.assertRegexpMatches(read_file(pid_specific_log_file), """\
Fatal Python error: Aborted

Thread [^\n]+ \\(most recent call first\\):
""")
      # faulthandler.enable() only allows use of a single logging file at once for fatal tracebacks.
      self.assertEqual('', read_file(shared_log_file))

  def test_prints_traceback_on_sigusr2(self):
    with self._make_waiter_handle() as (workdir, waiter_handle):
      time.sleep(5)
      # Send SIGUSR2, then sleep so the signal handler from faulthandler.register() can run.
      os.kill(waiter_handle.process.pid, signal.SIGUSR2)
      time.sleep(1)
      # This target will wait forever, so kill the process and ensure its output is correct.
      os.kill(waiter_handle.process.pid, signal.SIGKILL)
      waiter_run = waiter_handle.join()
      self.assert_failure(waiter_run)
      self.assertRegexpMatches(waiter_run.stderr_data, """\
Current thread [^\n]+ \\(most recent call first\\):
""")

  def test_keyboardinterrupt_signals(self):
    for interrupt_signal in [signal.SIGINT, signal.SIGQUIT]:
      with self._send_signal_to_waiter_handle(interrupt_signal) as (workdir, waiter_run):
        self.assertIn('Interrupted by user.\n', waiter_run.stderr_data)

  def _lifecycle_stub_cmdline(self):
    # Load the testprojects pants-plugins to get some testing tasks and subsystems.
    testproject_backend_src_dir = os.path.join(
      get_buildroot(), 'testprojects/pants-plugins/src/python')
    testproject_backend_pkg_name = 'test_pants_plugin'
    lifecycle_stub_cmdline = [
      '--no-enable-pantsd',
      "--pythonpath=+['{}']".format(testproject_backend_src_dir),
      "--backend-packages=+['{}']".format(testproject_backend_pkg_name),
      # This task will always raise an exception.
      'lifecycle-stub-goal',
    ]

    return lifecycle_stub_cmdline

  def test_reset_exiter(self):
    """Test that when reset_exiter() is used that sys.excepthook uses the new Exiter."""
    lifecycle_stub_cmdline = self._lifecycle_stub_cmdline()

    # The normal Exiter will print the exception message on an unhandled exception.
    normal_exiter_run = self.run_pants(lifecycle_stub_cmdline)
    self.assert_failure(normal_exiter_run)
    self.assertIn('erroneous!', normal_exiter_run.stderr_data)
    self.assertNotIn('NEW MESSAGE', normal_exiter_run.stderr_data)

    # The exiter that gets added when this option is changed prints that option to stderr.
    changed_exiter_run = self.run_pants([
      "--lifecycle-stubs-add-exiter-message='{}'".format('NEW MESSAGE'),
    ] + lifecycle_stub_cmdline)
    self.assert_failure(changed_exiter_run)
    self.assertIn('erroneous!', changed_exiter_run.stderr_data)
    self.assertIn('NEW MESSAGE', changed_exiter_run.stderr_data)

  def test_reset_interactive_output_stream(self):
    """Test redirecting the terminal output stream to a separate file."""
    lifecycle_stub_cmdline = self._lifecycle_stub_cmdline()

    failing_pants_run = self.run_pants(lifecycle_stub_cmdline)
    self.assert_failure(failing_pants_run)
    self.assertIn('erroneous!', failing_pants_run.stderr_data)

    with temporary_dir() as tmpdir:
      some_file = os.path.join(tmpdir, 'some_file')
      safe_file_dump(some_file, b'', binary_mode=True)
      redirected_pants_run = self.run_pants([
        "--lifecycle-stubs-new-interactive-stream-output-file={}".format(some_file),
      ] + lifecycle_stub_cmdline)
      self.assert_failure(redirected_pants_run)
      # The Exiter prints the final error message to whatever the interactive output stream is set
      # to, so when it's redirected it won't be in stderr.
      self.assertNotIn('erroneous!', redirected_pants_run.stderr_data)
      self.assertIn('erroneous!', read_file(some_file))
