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

  def _get_log_file_paths(self, workdir, pants_run):
    pid_specific_log_file = ExceptionSink.exceptions_log_path(for_pid=pants_run.pid, in_dir=workdir)
    self.assertTrue(os.path.isfile(pid_specific_log_file))

    shared_log_file = ExceptionSink.exceptions_log_path(in_dir=workdir)
    self.assertTrue(os.path.isfile(shared_log_file))

    self.assertNotEqual(pid_specific_log_file, shared_log_file)

    return (pid_specific_log_file, shared_log_file)

  def _assert_graceful_signal_log_matches(self, pid, signum, signame, contents):
    self.assertRegex(contents, """\
timestamp: ([^\n]+)
process title: ([^\n]+)
sys\\.argv: ([^\n]+)
pid: {pid}
Signal {signum} \\({signame}\\) was raised\\. Exiting with failure\\.
""".format(pid=pid, signum=signum, signame=signame))
    # Ensure we write all output such as stderr and reporting files before closing any streams.
    self.assertNotIn(
      'Exception message: I/O operation on closed file.',
      contents)

  @contextmanager
  def _make_waiter_handle(self):
    with temporary_dir() as tmpdir:
      # The path is required to end in '.pants.d'. This is validated in
      # GoalRunner#is_valid_workdir().
      workdir = os.path.join(tmpdir, '.pants.d')
      safe_mkdir(workdir)
      arrive_file = os.path.join(tmpdir, 'arrived')
      await_file = os.path.join(tmpdir, 'await')
      waiter_handle = self.run_pants_with_workdir_without_waiting([
        '--no-enable-pantsd',
        'run', 'testprojects/src/python/coordinated_runs:phaser',
        '--', arrive_file, await_file
      ], workdir)

      # Wait for testprojects/src/python/coordinated_runs:phaser to be running.
      while not os.path.exists(arrive_file):
        time.sleep(0.1)

      def join():
        touch(await_file)
        return waiter_handle.join()

      yield (workdir, waiter_handle.process.pid, join)

  @contextmanager
  def _send_signal_to_waiter_handle(self, signum):
    # This needs to be a contextmanager as well, because workdir may be temporary.
    with self._make_waiter_handle() as (workdir, pid, join):
      os.kill(pid, signum)
      waiter_run = join()
      self.assert_failure(waiter_run)
      # Return the (failed) pants execution result.
      yield (workdir, waiter_run)

  def test_dumps_logs_on_signal(self):
    """Send signals which are handled, but don't get converted into a KeyboardInterrupt."""
    signal_names = {
      signal.SIGQUIT: 'SIGQUIT',
      signal.SIGTERM: 'SIGTERM',
    }
    for (signum, signame) in signal_names.items():
      with self._send_signal_to_waiter_handle(signum) as (workdir, waiter_run):
        self.assertRegex(waiter_run.stderr_data, """\
timestamp: ([^\n]+)
Signal {signum} \\({signame}\\) was raised\\. Exiting with failure\\.
""".format(signum=signum, signame=signame))
        # Check that the logs show a graceful exit by SIGTERM.
        pid_specific_log_file, shared_log_file = self._get_log_file_paths(workdir, waiter_run)
        self._assert_graceful_signal_log_matches(
          waiter_run.pid, signum, signame, read_file(pid_specific_log_file))
        self._assert_graceful_signal_log_matches(
          waiter_run.pid, signum, signame, read_file(shared_log_file))
