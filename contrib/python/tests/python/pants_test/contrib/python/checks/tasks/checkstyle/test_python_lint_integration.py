# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_daemon


class PythonReplIntegrationTest(PantsRunIntegrationTest):

  TESTPROJECT = "./pants lint testprojects/src/python/interpreter_selection/python_3_selection_testing{}"

  @ensure_daemon
  def test_run_lint_py2_only(self):
    command = ['lint', TESTPROJECT.format(':main_py2')]
    pants_run = self.run_pants(command=command)
    output_lines = pants_run.stdout_data.rstrip().split('\n')
    self.assertIn('Success', output_lines)

  @ensure_daemon
  def test_lint_fails_on_incompatible_closure(self):
    command = ['lint', TESTPROJECT.format('::')]
    pants_run = self.run_pants(command=command)
    output_lines = pants_run.stdout_data.rstrip().split('\n')
    self.assertIn('Failed', output_lines)
