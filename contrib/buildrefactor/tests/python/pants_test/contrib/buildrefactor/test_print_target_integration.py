# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PrintTargetIntegrationTest(PantsRunIntegrationTest):
  """Test Peek goal functionality

      $./pants test contrib/buildrefactor/tests/python/pants_test/contrib/buildrefactor:print_target_integration
  """

  def test_print_name(self):
    print_target_print_run = self.run_pants(['print-target',
      'testprojects/tests/java/org/pantsbuild/testproject/buildrefactor/x:X'])

    self.assertIn('\'X\' found in BUILD file.', print_target_print_run.stdout_data)
    self.assertIn('name = "X"', print_target_print_run.stdout_data)

  def test_print_invalid_name(self):
    print_target_invalid_name_run = self.run_pants(['print-target',
    'testprojects/tests/java/org/pantsbuild/testproject/buildrefactor/x:Y'])

    self.assertIn('ResolveError: "Y" was not found in namespace', print_target_invalid_name_run.stderr_data)
    self.assertIn('Did you mean one of:\n        :X', print_target_invalid_name_run.stderr_data)

  def test_print_line_number(self):
    print_target_line_number_run = self.run_pants(['print-target',
      '--line-number',
      'testprojects/tests/java/org/pantsbuild/testproject/buildrefactor/x:X'])

    self.assertIn('Line numbers: 4-6.', print_target_line_number_run.stdout_data)
    self.assertIn('name = "X"', print_target_line_number_run.stdout_data)

  def test_multiple_targets(self):
    print_target_multiple_targets_run = self.run_pants(['print-target',
      'testprojects/tests/java/org/pantsbuild/testproject/buildrefactor/x:X',
      'tmp:tmp'])

    self.assertIn('FAILURE: More than one target specified:', print_target_multiple_targets_run.stdout_data or 
      print_target_multiple_targets_run.stderr_data)
