# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sys
import time

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.pexrc_util import setup_pexrc_with_pex_python_path


class PytestRunIntegrationTest(PantsRunIntegrationTest):
  testproject = 'testprojects/src/python/interpreter_selection'

  def test_pytest_run_timeout_succeeds(self):
    pants_run = self.run_pants(['clean-all',
                                'test.pytest',
                                '--test-pytest-options=-k within_timeout',
                                '--timeout-default=2',
                                'testprojects/tests/python/pants/timeout:exceeds_timeout'])
    self.assert_success(pants_run)

  def test_pytest_run_conftest_succeeds(self):
    pants_run = self.run_pants(['clean-all',
                                'test.pytest',
                                'testprojects/tests/python/pants/conf_test'])
    self.assert_success(pants_run)

  def test_pytest_run_timeout_fails(self):
    start = time.time()
    pants_run = self.run_pants(['clean-all',
                                'test.pytest',
                                '--test-pytest-coverage=auto',
                                '--test-pytest-options=-k exceeds_timeout',
                                '--test-pytest-timeout-default=1',
                                '--cache-test-pytest-ignore',
                                'testprojects/tests/python/pants/timeout:exceeds_timeout'])
    end = time.time()
    self.assert_failure(pants_run)

    # Ensure that the failure took less than 100 seconds to run to allow for test overhead.
    self.assertLess(end - start, 100)

    # Ensure that a warning about coverage reporting was emitted.
    self.assertIn("No .coverage file was found! Skipping coverage reporting", pants_run.stdout_data)

    # Ensure that the timeout message triggered.
    self.assertIn("FAILURE: Timeout of 1 seconds reached.", pants_run.stdout_data)

  def test_pytest_run_timeout_cant_terminate(self):
    start = time.time()
    pants_run = self.run_pants(['clean-all',
                                'test.pytest',
                                '--test-pytest-timeout-terminate-wait=2',
                                '--test-pytest-timeout-default=1',
                                '--test-pytest-coverage=auto',
                                '--cache-test-pytest-ignore',
                                'testprojects/tests/python/pants/timeout:ignores_terminate'])
    end = time.time()
    self.assert_failure(pants_run)

    # Ensure that the failure took less than 100 seconds to run to allow for test overhead.
    self.assertLess(end - start, 100)

    # Ensure that a warning about coverage reporting was emitted.
    self.assertIn("No .coverage file was found! Skipping coverage reporting", pants_run.stdout_data)

    # Ensure that the timeout message triggered.
    self.assertIn("FAILURE: Timeout of 1 seconds reached.", pants_run.stdout_data)

    # Ensure that the warning about killing triggered.
    self.assertIn("WARN] Timed out test did not terminate gracefully after 2 seconds, "
                  "killing...", pants_run.stderr_data)

  def test_pytest_explicit_coverage(self):
    with temporary_dir(cleanup=False) as coverage_dir:
      pants_run = self.run_pants(['clean-all',
                                  'test.pytest',
                                  '--test-pytest-coverage=pants',
                                  '--test-pytest-coverage-output-dir={}'.format(coverage_dir),
                                  'testprojects/tests/python/pants/constants_only'])
      self.assert_success(pants_run)
      self.assertTrue(os.path.exists(os.path.join(coverage_dir, 'coverage.xml')))

  def test_pytest_with_profile(self):
    with temporary_dir() as profile_dir:
      prof = os.path.join(profile_dir, 'pants.prof')
      pants_run = self.run_pants(['clean-all',
                                  'test.pytest',
                                  'testprojects/tests/python/pants/constants_only:constants_only'],
                                 extra_env={'PANTS_PROFILE': prof})
      self.assert_success(pants_run)
      # Note that the subprocess profile mechanism will add a ".0" to the profile path.
      # We won't see a profile at prof itself because PANTS_PROFILE wasn't set when the
      # current process started.
      self.assertTrue(os.path.exists('{}.0'.format(prof)))

  def test_pants_test_interpreter_selection_with_pexrc(self):
    """Test the pants test goal with intepreters selected from a PEX_PYTHON_PATH
    defined in a pexrc file on disk.

    """
    py27 = '2.7'
    py3 = '3'
    if self.has_python_version(py27) and self.has_python_version(py3):
      print('Found both python {} and python {}. Running test.'.format(py27, py3))
      py27_path, py3_path = self.python_interpreter_path(py27), self.python_interpreter_path(py3)
      with setup_pexrc_with_pex_python_path(os.path.join(os.path.dirname(sys.argv[0]), '.pexrc'), [py27_path, py3_path]):
        with temporary_dir() as interpreters_cache:
          pants_ini_config = {'python-setup': {'interpreter_cache_dir': interpreters_cache}}
          pants_run_27 = self.run_pants(
            command=['test', '{}:test_py2'.format(os.path.join(self.testproject, 'python_3_selection_testing'))],
            config=pants_ini_config
          )
          self.assert_success(pants_run_27)
          pants_run_3 = self.run_pants(
            command=['test', '{}:test_py3'.format(os.path.join(self.testproject, 'python_3_selection_testing'))],
            config=pants_ini_config
          )
          self.assert_success(pants_run_3)
    else:
      print('Could not find both python {} and python {} on system. Skipping.'.format(py27, py3))
      self.skipTest('Missing neccesary Python interpreters on system.')
