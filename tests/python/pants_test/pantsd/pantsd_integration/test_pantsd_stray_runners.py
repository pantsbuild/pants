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
  def test_pantsd_stray_runners(self):
    # Allow env var overrides for local stress testing.
    attempts = int(os.environ.get('PANTS_TEST_PANTSD_STRESS_ATTEMPTS', 20))
    cmd = os.environ.get('PANTS_TEST_PANTSD_STRESS_CMD', 'help').split()

    with no_lingering_process_by_command('pantsd'):
      with self.pantsd_successful_run_context('debug') as (pantsd_run, checker, _, _):
        pantsd_run(cmd)
        checker.assert_started()
        for _ in range(attempts):
          pantsd_run(cmd)
          checker.assert_running()
        # The runner can sometimes exit more slowly than the thin client caller.
        time.sleep(3)
