# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PytestRunIntegrationTest(PantsRunIntegrationTest):
  def test_pytest_run_timeout_succeeds(self):
    pants_run = self.run_pants(['clean-all', 'test.pytest',  'testprojects/tests/python/pants/timeout:passing_target'])
    self.assert_success(pants_run)

  def test_pytest_run_timeout_fails(self):
    pants_run = self.run_pants(['clean-all', 'test.pytest',  'testprojects/tests/python/pants/timeout:failing_target'])
    self.assert_failure(pants_run)

    # Make sure that the failure took only 1 second to run
    self.assertIn("FAILURE: After 1 seconds: Timeout of 1 seconds reached", pants_run.stdout_data)
