# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


TEST_DIR = 'testprojects/src/scala/org/pantsbuild/testproject'


class ScalaFmtIntegrationTests(PantsRunIntegrationTest):
  def test_scalafmt_fail(self):
    target = '{}:badScalaStyle'.format(TEST_DIR)
    #test should fail because of style error
    failing_test = self.run_pants(['test', target])
    self.assert_failure(failing_test)

  # def test_scalafmt_success(self):
  #   #Verifies that checked in Scala testprojects pass scalafmt"
  #   for project in ('emptyscala', 'scalac'):
  #     target = '{}/{}::'.format(TEST_DIR, project)
  #     #test should pass because of style error
  #     passing_test = self.run_pants(['test', target])
  #     self.assert_success(passing_test)
