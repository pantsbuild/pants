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

  def test_keyboardinterrupt(self):
    with self._send_signal_to_waiter_handle(signal.SIGINT) as (_, waiter_run):
      self.assertIn(
        'Interrupted by user:\nUser interrupted execution with control-c!',
        waiter_run.stderr_data)
