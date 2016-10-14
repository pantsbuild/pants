# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


TEST_DIR = 'testprojects/src/scala/org/pantsbuild/testproject'


class ScalaFmtIntegrationTests(PantsRunIntegrationTest):
  def test_scalafmt_fail(self):
    target = '{}/badscalastyle::'.format(TEST_DIR)
    # test should fail because of style error.
    failing_test = self.run_pants(['compile', target],
      {'compile.scalafmt':{'skip': 'False'}})

    self.assert_failure(failing_test)

  def test_scalafmt_disabled(self):
    target = '{}/badscalastyle::'.format(TEST_DIR)
    # test should pass because of scalafmt disabled.
    failing_test = self.run_pants(['compile', target],
      {'compile.scalafmt':{'skip': 'True'}})

    self.assert_success(failing_test)

  def test_scalafmt_format(self):

    # take a snapshot of the file which we can write out 
    # after the test finishes executing. 
    test_file_name = '{}/badscalastyle/BadScalaStyle.scala'.format(TEST_DIR)
    f = open(test_file_name, 'r')
    contents = f.read()
    f.close()


    target = '{}/badscalastyle::'.format(TEST_DIR)
    fmt_result = self.run_pants(['fmt', target],
      {'fmt.scalafmt':{'skip': 'False'}})

    self.assert_success(fmt_result)

    test_fmt= self.run_pants(['compile', target],
      {'compile.scalafmt':{'skip': 'False'}})

    self.assert_success(test_fmt)

    # restore the file to its original state
    f = open(test_file_name, 'w')
    f.write(contents)
    f.close()

