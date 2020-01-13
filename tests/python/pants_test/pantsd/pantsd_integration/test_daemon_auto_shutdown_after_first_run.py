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

  def test_daemon_auto_shutdown_after_first_run(self):
    config = {'GLOBAL': {'shutdown_pantsd_after_run': True}}
    with self.pantsd_test_context(extra_config=config) as (workdir, config, checker):
      wait_handle = self.run_pants_with_workdir_without_waiting(
        ['list'],
        workdir,
        config,
      )

      # TODO(#6574, #7330): We might have a new default timeout after these are resolved.
      checker.assert_started(timeout=16)
      pantsd_processes = checker.runner_process_context.current_processes()
      pants_run = wait_handle.join()
      self.assert_success(pants_run)

      # Permit enough time for the process to terminate in CI
      time.sleep(5)

      for process in pantsd_processes:
        self.assertFalse(process.is_running())
