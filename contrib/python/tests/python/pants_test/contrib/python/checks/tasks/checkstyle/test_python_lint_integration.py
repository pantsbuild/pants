# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PythonLintIntegrationTest(PantsRunIntegrationTest):

  TESTPROJECT = "testprojects/src/python/interpreter_selection/python_3_selection_testing{}"

  def test_lint_runs_for_py2_only(self):
    command = ['lint', self.TESTPROJECT.format(':main_py2')]
    pants_run = self.run_pants(command=command)
    self.assertIn('Style issues found', pants_run.stdout_data)

  def test_lint_skips_for_py3_only(self):
    command = ['lint', self.TESTPROJECT.format(':main_py3')]
    pants_run = self.run_pants(command=command)
    # Verify Python 3 lint is skipped.
    self.assertIn('Linting is currently disabled', pants_run.stdout_data)
    # Identify that the Python 2 targets are not linted.
    self.assertNotIn('Style issues found', pants_run.stdout_data)

  def test_lint_fails_on_incompatible_closure(self):
    command = ['lint', self.TESTPROJECT.format('::')]
    pants_run = self.run_pants(command=command)
    # Verify Python 3 lint is skipped.
    self.assertIn('Linting is currently disabled', pants_run.stdout_data)
    # Identify that the Python 2 targets are linted.
    self.assertIn('Style issues found', pants_run.stdout_data)
