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

  def test_inner_runs_dont_deadlock(self):
    """
    Create a pantsd run that calls testprojects/src/python/nested_runs with the appropriate
    bootstrap options to avoid restarting pantsd.

    Regression test for issue https://github.com/pantsbuild/pants/issues/7881
    When a run under pantsd calls pants with pantsd inside it, the inner run will time out
    waiting for the outer run to end.

    NB: testprojects/src/python/nested_runs assumes that the pants.ini file is in ${workdir}/pants.ini
    """
    config = {
      'GLOBAL': {
        'pantsd_timeout_when_multiple_invocations': 1,
      }
    }
    with self.pantsd_successful_run_context(extra_config=config) as (pantsd_run, checker, workdir, _):
      result = pantsd_run(['run', 'testprojects/src/python/nested_runs', '--', workdir], expected_runs=2)
      checker.assert_started()
      self.assert_success(result)
      self.assertNotIn("Another pants invocation is running", result.stderr_data)
