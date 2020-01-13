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

  def test_pantsd_launch_env_var_is_not_inherited_by_pantsd_runner_children(self):
    with self.pantsd_test_context() as (workdir, pantsd_config, checker):
      with environment_as(NO_LEAKS='33'):
        self.assert_success(
          self.run_pants_with_workdir(
            ['help'],
            workdir,
            pantsd_config)
        )
        checker.assert_started()

      self.assert_failure(
        self.run_pants_with_workdir(
          ['-q', 'run', 'testprojects/src/python/print_env', '--', 'NO_LEAKS'],
          workdir,
          pantsd_config
        )
      )
      checker.assert_running()
