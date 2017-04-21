# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import time
import unittest

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PytestRunIntegrationTest(PantsRunIntegrationTest):
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

  @unittest.skip('https://github.com/pantsbuild/pants/issues/3255')
  def test_pytest_run_timeout_fails(self):
    start = time.time()
    pants_run = self.run_pants(['clean-all',
                                'test.pytest',
                                '--test-pytest-coverage=auto',
                                '--test-pytest-options=-k exceeds_timeout',
                                '--timeout-default=1',
                                'testprojects/tests/python/pants/timeout:exceeds_timeout'])
    end = time.time()
    self.assert_failure(pants_run)

    # Ensure that the failure took less than 20 seconds to run.
    self.assertLess(end - start, 20)

    # Ensure that a warning about coverage reporting was emitted.
    self.assertIn("No .coverage file was found! Skipping coverage reporting", pants_run.stderr_data)

    # Ensure that the timeout message triggered.
    self.assertIn("FAILURE: Timeout of 1 seconds reached", pants_run.stdout_data)

  @unittest.skip('https://github.com/pantsbuild/pants/issues/3255')
  def test_pytest_run_timeout_cant_terminate(self):
    start = time.time()
    terminate_wait = 2
    pants_run = self.run_pants(['clean-all',
                                'test.pytest',
                                '--test-pytest-coverage=auto',
                                '--test-pytest-timeout-terminate-wait=%d' % terminate_wait,
                                '--timeout-default=1',
                                'testprojects/tests/python/pants/timeout:ignores_terminate'])
    end = time.time()
    self.assert_failure(pants_run)

    # Ensure that the failure took less than 20 seconds to run.
    self.assertLess(end - start, 20)

    # Ensure that a warning about coverage reporting was emitted.
    self.assertIn("No .coverage file was found! Skipping coverage reporting", pants_run.stderr_data)

    # Ensure that the timeout message triggered.
    self.assertIn("FAILURE: Timeout of 1 seconds reached", pants_run.stdout_data)

    # Ensure that the warning about killing triggered.
    self.assertIn("WARN] Timed out test did not terminate gracefully after {} seconds, "
                  "killing...".format(terminate_wait), pants_run.stderr_data)

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
