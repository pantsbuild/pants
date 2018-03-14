# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


TEST_DIR = 'contrib/googlejavaformat/testprojects/src/java/org/pantsbuild/testproject'


class GoogleJavaFormatIntegrationTests(PantsRunIntegrationTest):
  def test_googlejavaformat_fail(self):
    target = '{}/badgooglejavaformat'.format(TEST_DIR)
    # test should fail because of style error.
    failing_test = self.run_pants(['lint', target],
      {'lint.google-java-format':{'skip':'False'}})
    self.assert_failure(failing_test)

  def test_disabled(self):
    target = '{}/badgooglejavaformat'.format(TEST_DIR)
    # test should pass because check is disabled.
    failing_test = self.run_pants(['lint', target],
      {'lint.google-java-format': {'skip':'True'}})
    self.assert_success(failing_test)

  def format_file_and_verify_fmt(self, options):
    # take a snapshot of the file which we can write out
    # after the test finishes executing.
    test_file_name = '{}/badscalastyle/BadGoogleJavaFormat.java'.format(TEST_DIR)
    with open(test_file_name, 'r') as f:
      contents = f.read()

    try:
      # format an incorrectly formatted file.
      target = '{}/badgooglejavaformat'.format(TEST_DIR)
      fmt_result = self.run_pants(['fmt', target], {'fmt.google-java-format':options})
      self.assert_success(fmt_result)

      # verify that the lint check passes.
      test_fmt = self.run_pants(['lint', target], {'lint.google-java-format':options})
      self.assert_success(test_fmt)
    finally:
      # restore the file to its original state.
      f = open(test_file_name, 'w')
      f.write(contents)
      f.close()
