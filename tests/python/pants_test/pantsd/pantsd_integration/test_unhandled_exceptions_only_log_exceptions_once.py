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
  def test_unhandled_exceptions_only_log_exceptions_once(self):
    """
    Tests that the unhandled exceptions triggered by LocalPantsRunner instances don't manifest
    as a PantsRunFinishedWithFailureException.

    That is, that we unset the global Exiter override set by LocalPantsRunner before we try to log the exception.

    This is a regression test for the most glaring case of https://github.com/pantsbuild/pants/issues/7597.
    """
    with self.pantsd_run_context(success=False) as (pantsd_run, checker, _, _):
      result = pantsd_run(['run', 'testprojects/src/python/bad_requirements:use_badreq'])
      checker.assert_running()
      self.assert_failure(result)
      # Assert that the desired exception has been triggered once.
      self.assertIn(
        """Exception message: Could not satisfy all requirements for badreq==99.99.99:\n    badreq==99.99.99""",
        result.stderr_data,
      )
      # Assert that it has only been triggered once.
      self.assertNotIn(
        'During handling of the above exception, another exception occurred:',
        result.stderr_data,
      )
      self.assertNotIn(
        'pants.bin.daemon_pants_runner._PantsRunFinishedWithFailureException: Terminated with 1',
        result.stderr_data,
      )
