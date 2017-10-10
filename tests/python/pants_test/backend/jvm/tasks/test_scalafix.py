# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


TEST_DIR = 'testprojects/src/scala/org/pantsbuild/testproject'


class ScalaFixIntegrationTest(PantsRunIntegrationTest):

  _rules = {'rules': 'ProcedureSyntax'}
  _options = {
      'lint.scalafix': _rules,
      'fmt.scalafix': _rules,
      'lint.scalastyle': {'skip': True}
    }

  @classmethod
  def hermetic(cls):
    return True

  def test_scalafix_fail(self):
    target = '{}/procedure_syntax'.format(TEST_DIR)
    # lint should fail because the rule has an impact.
    failing_test = self.run_pants(['lint', target], self._options)
    self.assert_failure(failing_test)

  def test_scalafix_disabled(self):
    # take a snapshot of the file which we can write out
    # after the test finishes executing.
    test_file_name = '{}/procedure_syntax/ProcedureSyntax.scala'.format(TEST_DIR)
    with open(test_file_name, 'r') as f:
      contents = f.read()

    try:
      # format an incorrectly formatted file.
      target = '{}/procedure_syntax'.format(TEST_DIR)
      fmt_result = self.run_pants(['fmt', target], self._options)
      self.assert_success(fmt_result)

      # verify that the lint check passes.
      test_fix = self.run_pants(['lint', target], self._options)
      self.assert_success(test_fix)
    finally:
      # restore the file to its original state.
      f = open(test_file_name, 'w')
      f.write(contents)
      f.close()
