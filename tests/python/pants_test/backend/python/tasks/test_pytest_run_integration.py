# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import time

from pants.util.contextutil import temporary_dir
from pants_test.backend.python.interpreter_selection_utils import (PY_3, PY_27,
                                                                   python_interpreter_path,
                                                                   skip_unless_python3_present,
                                                                   skip_unless_python27_and_python3_present,
                                                                   skip_unless_python27_present)
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.pexrc_util import setup_pexrc_with_pex_python_path


class PytestRunIntegrationTest(PantsRunIntegrationTest):
  testproject = 'testprojects/src/python/interpreter_selection'

  # NB: Occasionally running a test in CI may take multiple seconds. The tests in this file which
  # use the --timeout-default argument are not testing for performance regressions, but just for
  # correctness of timeout behavior, so we set this to a higher value to avoid flakiness.
  _non_flaky_timeout_seconds = 5

  def test_pytest_run_timeout_succeeds(self):
    pants_run = self.run_pants(['clean-all',
                                'test.pytest',
                                '--timeout-default={}'.format(self._non_flaky_timeout_seconds),
                                'testprojects/tests/python/pants/timeout:exceeds_timeout',
                                '--',
                                '-kwithin_timeout'])
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
                                '--coverage=auto',
                                '--timeout-default=1',
                                '--cache-ignore',
                                'testprojects/tests/python/pants/timeout:exceeds_timeout',
                                '--',
                                '-kexceeds_timeout'])
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
                                '--timeout-terminate-wait=2',
                                '--timeout-default={}'.format(self._non_flaky_timeout_seconds),
                                '--coverage=auto',
                                '--cache-ignore',
                                'testprojects/tests/python/pants/timeout:ignores_terminate'])
    end = time.time()
    self.assert_failure(pants_run)

    # Ensure that the failure took less than 100 seconds to run to allow for test overhead.
    self.assertLess(end - start, 100)

    # Ensure that a warning about coverage reporting was emitted.
    self.assertIn("No .coverage file was found! Skipping coverage reporting", pants_run.stdout_data)

    # Ensure that the timeout message triggered.
    self.assertIn("FAILURE: Timeout of 5 seconds reached.", pants_run.stdout_data)

    # Ensure that the warning about killing triggered.
    self.assertIn("Timed out test did not terminate gracefully after 2 seconds, "
                  "killing...", pants_run.stdout_data)

  def test_pytest_run_killed_by_signal(self):
    start = time.time()
    pants_run = self.run_pants(['clean-all',
                                'test.pytest',
                                '--timeout-terminate-wait=2',
                                '--timeout-default={}'.format(self._non_flaky_timeout_seconds),
                                '--cache-ignore',
                                'testprojects/tests/python/pants/timeout:terminates_self'])
    end = time.time()
    self.assert_failure(pants_run)

    # Ensure that the failure took less than 100 seconds to run to allow for test overhead.
    self.assertLess(end - start, 100)

    # Ensure that we get a message indicating the abnormal exit.
    self.assertIn("FAILURE: Test was killed by signal", pants_run.stdout_data)

  def test_pytest_explicit_coverage(self):
    with temporary_dir() as coverage_dir:
      pants_run = self.run_pants(['clean-all',
                                  'test.pytest',
                                  '--coverage=pants',
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

  @skip_unless_python27_and_python3_present
  def test_pants_test_interpreter_selection_with_pexrc(self):
    """Test the pants test goal with intepreters selected from a PEX_PYTHON_PATH
    defined in a pexrc file on disk.
    """
    py27_path, py3_path = python_interpreter_path(PY_27), python_interpreter_path(PY_3)
    with setup_pexrc_with_pex_python_path([py27_path, py3_path]):
      with temporary_dir() as interpreters_cache:
        pants_ini_config = {
          'python-setup': {
            'interpreter_cache_dir': interpreters_cache,
            'interpreter_search_paths': ['<PEXRC>'],
          }
        }
        pants_run_27 = self.run_pants(
          command=['test', '{}:test_py2'.format(os.path.join(self.testproject,
                                                             'python_3_selection_testing'))],
          config=pants_ini_config
        )
        self.assert_success(pants_run_27)
        pants_run_3 = self.run_pants(
          command=['test', '{}:test_py3'.format(os.path.join(self.testproject,
                                                             'python_3_selection_testing'))],
          config=pants_ini_config
        )
        self.assert_success(pants_run_3)

  @skip_unless_python27_present
  def test_pants_test_interpreter_selection_with_option_2(self):
    """
    Test that the pants test goal properly constrains the SelectInterpreter task to Python 2
    using the '--python-setup-interpreter-constraints' option.
    """
    with temporary_dir() as interpreters_cache:
      pants_ini_config = {
        'python-setup': {
          'interpreter_constraints': ['CPython>=2.7,<4'],
          'interpreter_cache_dir': interpreters_cache,
        }
      }
      pants_run_2 = self.run_pants(
        command=[
          'test',
          '{}:test_py2'.format(os.path.join(self.testproject,'python_3_selection_testing')),
          '--python-setup-interpreter-constraints=["CPython<3"]',
        ],
        config=pants_ini_config
      )
      self.assert_success(pants_run_2)

  @skip_unless_python3_present
  def test_pants_test_interpreter_selection_with_option_3(self):
    """
    Test that the pants test goal properly constrains the SelectInterpreter task to Python 3
    using the '--python-setup-interpreter-constraints' option.
    """
    with temporary_dir() as interpreters_cache:
      pants_ini_config = {
        'python-setup': {
          'interpreter_constraints': ['CPython>=2.7,<4'],
          'interpreter_cache_dir': interpreters_cache,
        }
      }
      pants_run_3 = self.run_pants(
            command=[
              'test',
              '{}:test_py3'.format(os.path.join(self.testproject, 'python_3_selection_testing')),
              '--python-setup-interpreter-constraints=["CPython>=3"]',
            ],
            config=pants_ini_config
          )
      self.assert_success(pants_run_3)
