# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class AliasTargetIntegrationTest(PantsRunIntegrationTest):

  test_module = 'testprojects/src/java/org/pantsbuild/testproject/aliases'

  def test_jvm_binary_alias(self):
    test_run = self.run_pants([
      'run',
      '{}:convenient'.format(self.test_module),
    ])
    self.assert_success(test_run)
    self.assertIn('AliasedBinaryMain is up and running.', test_run.stdout_data)

  def test_intransitive_target_alias(self):
    test_run = self.run_pants([
      'run',
      '{}:run-use-intransitive'.format(self.test_module),
    ])
    self.assert_success(test_run)

  def test_alias_missing_target(self):
    with self.file_renamed(self.test_module, 'TEST_NO_TARGET', 'BUILD.test'):
      test_run = self.run_pants(['bootstrap', '{}::'.format(self.test_module)])
      self.assert_failure(test_run)
      self.assertIn('must have a "target"', test_run.stderr_data)
      self.assertIn('aliases:missing-target', test_run.stderr_data)

  def test_alias_missing_name(self):
    with self.file_renamed(self.test_module, 'TEST_NO_NAME', 'BUILD.test'):
      test_run = self.run_pants(['bootstrap', '{}::'.format(self.test_module)])
      self.assert_failure(test_run)
      self.assertIn('aliases:?', test_run.stderr_data)
