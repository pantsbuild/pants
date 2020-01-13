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

  def test_pantsd_invalidation_stale_sources(self):
    test_path = 'tests/python/pants_test/daemon_correctness_test_0001'
    test_build_file = os.path.join(test_path, 'BUILD')
    test_src_file = os.path.join(test_path, 'some_file.py')
    has_source_root_regex = r'"source_root": ".*/{}"'.format(test_path)
    export_cmd = ['export', test_path]

    try:
      with self.pantsd_successful_run_context() as (pantsd_run, checker, workdir, _):
        safe_mkdir(test_path, clean=True)

        pantsd_run(['help'])
        checker.assert_started()

        safe_file_dump(test_build_file, "python_library(sources=globs('some_non_existent_file.py'))")
        result = pantsd_run(export_cmd)
        checker.assert_running()
        self.assertNotRegex(result.stdout_data, has_source_root_regex)

        safe_file_dump(test_build_file, "python_library(sources=globs('*.py'))")
        result = pantsd_run(export_cmd)
        checker.assert_running()
        self.assertNotRegex(result.stdout_data, has_source_root_regex)

        safe_file_dump(test_src_file, 'import this\n')
        result = pantsd_run(export_cmd)
        checker.assert_running()
        self.assertRegex(result.stdout_data, has_source_root_regex)
    finally:
      rm_rf(test_path)
