# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import time

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PytestRunIntegrationTest(PantsRunIntegrationTest):
  def test_pytest_run_timeout_succeeds(self):
    pants_run = self.run_pants(['clean-all',
                                'test.pytest',
                                '--test-pytest-options="-k sleep_short"',
                                '--timeout-default=2',
                                'testprojects/tests/python/pants/timeout:sleeping_target'])
    self.assert_success(pants_run)

  def test_pytest_run_timeout_fails(self):
    start = time.time()
    pants_run = self.run_pants(['clean-all',
                                'test.pytest',
                                '--test-pytest-options="-k sleep_long"',
                                '--timeout-default=1',
                                'testprojects/tests/python/pants/timeout:sleeping_target'])
    end = time.time()
    self.assert_failure(pants_run)

    # Ensure that the failure took less than 120 seconds to run.
    self.assertLess(end - start, 120)

    # Ensure that the timeout message triggered.
    self.assertIn("FAILURE: Timeout of 1 seconds reached", pants_run.stdout_data)
