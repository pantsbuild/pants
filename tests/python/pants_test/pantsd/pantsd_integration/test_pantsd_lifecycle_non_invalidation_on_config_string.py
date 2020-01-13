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

  def test_pantsd_lifecycle_non_invalidation_on_config_string(self):
    with temporary_dir() as dist_dir_root, temporary_dir() as config_dir:
      config_files = [
        os.path.abspath(os.path.join(config_dir, f'pants.ini.{i}')) for i in range(2)
      ]
      for config_file in config_files:
        print(f'writing {config_file}')
        with open(config_file, 'w') as fh:
          fh.write(f"[GLOBAL]\npants_distdir: {os.path.join(dist_dir_root, 'v1')}\n")

      invalidating_config = os.path.join(config_dir, 'pants.ini.invalidates')
      with open(invalidating_config, 'w') as fh:
        fh.write(f"[GLOBAL]\npants_distdir: {os.path.join(dist_dir_root, 'v2')}\n")

      with self.pantsd_successful_run_context() as (pantsd_run, checker, _, _):
        variants = [[f'--pants-config-files={f}', 'help'] for f in config_files]
        pantsd_pid = None
        for cmd in itertools.chain(*itertools.repeat(variants, 2)):
          pantsd_run(cmd)
          if not pantsd_pid:
            pantsd_pid = checker.assert_started()
          else:
            checker.assert_running()

        pantsd_run([f'--pants-config-files={invalidating_config}', 'help'])
        self.assertNotEqual(pantsd_pid, checker.assert_started())
