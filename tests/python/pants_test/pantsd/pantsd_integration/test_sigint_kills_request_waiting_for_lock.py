# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import datetime
import itertools
import os
import re
import signal
import threading
import time
import unittest
from textwrap import dedent

import pytest

from pants.testutil.pants_run_integration_test import read_pantsd_log
from pants.testutil.process_test_util import no_lingering_process_by_command
from pants.util.contextutil import environment_as, temporary_dir, temporary_file
from pants.util.dirutil import rm_rf, safe_file_dump, safe_mkdir, safe_open, touch
from pants_test.pantsd.pantsd_integration_test_base import PantsDaemonIntegrationTestBase


def launch_file_toucher(f):
  """Launch a loop to touch the given file, and return a function to call to stop and join it."""
  if not os.path.isfile(f):
    raise AssertionError('Refusing to touch a non-file.')

  halt = threading.Event()
  def file_toucher():
    while not halt.isSet():
      touch(f)
      time.sleep(1)
  thread = threading.Thread(target=file_toucher)
  thread.daemon = True
  thread.start()

  def join():
    halt.set()
    thread.join(timeout=10)

  return join


class TestPantsDaemonIntegration(PantsDaemonIntegrationTestBase):
  def test_sigint_kills_request_waiting_for_lock(self):
    """
    Test that, when a pailgun request is blocked waiting for another one to end,
    sending SIGINT to the blocked run will kill it.

    Regression test for issue: #7920
    """
    config = {'GLOBAL': {
      'pantsd_timeout_when_multiple_invocations': -1,
      'level': 'debug'
    }}
    with self.pantsd_test_context(extra_config=config) as (workdir, config, checker):
      # Run a repl, so that any other run waiting to acquire the daemon lock waits forever.
      first_run_handle = self.run_pants_with_workdir_without_waiting(
        command=['repl', 'examples/src/python/example/hello::'],
        workdir=workdir,
        config=config
      )
      checker.assert_started()
      checker.assert_running()

      blocking_run_handle = self.run_pants_with_workdir_without_waiting(
        command=['goals'],
        workdir=workdir,
        config=config
      )

      # Block until the second request is waiting for the lock.
      blocked = True
      while blocked:
        log = '\n'.join(read_pantsd_log(workdir))
        if "didn't aquire the lock on the first try, polling." in log:
          blocked = False
        # NB: This sleep is totally deterministic, it's just so that we don't spend too many cycles
        # busy waiting.
        time.sleep(0.1)

      # Sends SIGINT to the run that is waiting.
      blocking_run_client_pid = blocking_run_handle.process.pid
      os.kill(blocking_run_client_pid, signal.SIGINT)
      blocking_run_handle.join()

      # Check that pantsd is still serving the other request.
      checker.assert_running()

      # Send exit() to the repl, and exit it.
      result = first_run_handle.join(stdin_data='exit()')
      self.assert_success(result)
      checker.assert_running()
