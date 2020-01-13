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

  # This is a regression test for a bug where we would incorrectly detect a cycle if two targets swapped their
  # dependency relationship (#7404).
  def test_dependencies_swap(self):
    template = dedent("""
        python_library(
          name = 'A',
          source = 'A.py',
          {a_deps}
        )

        python_library(
          name = 'B',
          source = 'B.py',
          {b_deps}
        )
        """)
    with self.pantsd_successful_run_context() as (pantsd_run, checker, _, _):
      with temporary_dir('.') as directory:
        safe_file_dump(os.path.join(directory, 'A.py'), mode='w')
        safe_file_dump(os.path.join(directory, 'B.py'), mode='w')

        if directory.startswith('./'):
          directory = directory[2:]

        def list_and_verify():
          result = pantsd_run(['list', f'{directory}:'])
          checker.assert_started()
          self.assert_success(result)
          expected_targets = {f'{directory}:{target}' for target in ('A', 'B')}
          self.assertEqual(expected_targets, set(result.stdout_data.strip().split('\n')))

        with open(os.path.join(directory, 'BUILD'), 'w') as f:
          f.write(template.format(a_deps='dependencies = [":B"],', b_deps=''))
        list_and_verify()

        with open(os.path.join(directory, 'BUILD'), 'w') as f:
          f.write(template.format(a_deps='', b_deps='dependencies = [":A"],'))
        list_and_verify()
