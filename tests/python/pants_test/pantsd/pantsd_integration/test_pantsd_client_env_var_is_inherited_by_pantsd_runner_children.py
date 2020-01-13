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

  def test_pantsd_client_env_var_is_inherited_by_pantsd_runner_children(self):
    EXPECTED_KEY = 'TEST_ENV_VAR_FOR_PANTSD_INTEGRATION_TEST'
    EXPECTED_VALUE = '333'
    with self.pantsd_successful_run_context() as (pantsd_run, checker, workdir, _):
      # First, launch the daemon without any local env vars set.
      pantsd_run(['help'])
      checker.assert_started()

      # Then, set an env var on the secondary call.
      # We additionally set the `HERMETIC_ENV` env var to allow the integration test harness
      # to pass this variable through.
      env = {
          EXPECTED_KEY: EXPECTED_VALUE,
          'HERMETIC_ENV': EXPECTED_KEY,
        }
      with environment_as(**env):
        result = pantsd_run(
          ['-q',
           'run',
           'testprojects/src/python/print_env',
           '--',
           EXPECTED_KEY]
        )
        checker.assert_running()

      self.assertEqual(EXPECTED_VALUE, ''.join(result.stdout_data).strip())
