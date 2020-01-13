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
  @pytest.mark.flaky(retries=1)  # https://github.com/pantsbuild/pants/issues/8193
  def test_pantsd_memory_usage(self):
    """Validates that after N runs, memory usage has increased by no more than X percent."""
    number_of_runs = 10
    max_memory_increase_fraction = 0.40  # TODO https://github.com/pantsbuild/pants/issues/7647
    with self.pantsd_successful_run_context() as (pantsd_run, checker, workdir, config):
      # NB: This doesn't actually run against all testprojects, only those that are in the chroot,
      # i.e. explicitly declared in this test file's BUILD.
      cmd = ['list', 'testprojects::']
      self.assert_success(pantsd_run(cmd))
      initial_memory_usage = checker.current_memory_usage()
      for _ in range(number_of_runs):
        self.assert_success(pantsd_run(cmd))
        checker.assert_running()

      final_memory_usage = checker.current_memory_usage()
      self.assertTrue(
          initial_memory_usage <= final_memory_usage,
          "Memory usage inverted unexpectedly: {} > {}".format(
            initial_memory_usage, final_memory_usage
          )
        )

      increase_fraction = (float(final_memory_usage) / initial_memory_usage) - 1.0
      self.assertTrue(
          increase_fraction <= max_memory_increase_fraction,
          "Memory usage increased more than expected: {} -> {}: {} actual increase (expected < {})".format(
            initial_memory_usage, final_memory_usage, increase_fraction, max_memory_increase_fraction
          )
        )
