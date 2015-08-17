# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from unittest import skipIf

from pants.java.distribution.distribution import Distribution
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


def missing_jvm(version):
  try:
    Distribution.locate(minimum_version=version, maximum_version='{}.9999'.format(version))
    return False
  except Distribution.Error:
    return True


class JunitRunIntegrationTest(PantsRunIntegrationTest):

  def _testjvms(self, spec_name):
    spec = 'testprojects/tests/java/org/pantsbuild/testproject/testjvms:{}'.format(spec_name)
    self.assert_success(self.run_pants(['clean-all', 'test.junit', '--strict-jvm-version', spec]))

  @skipIf(missing_jvm('1.8'), 'no java 1.8 installation on testing machine')
  def test_java_eight(self):
    self._testjvms('eight')

  @skipIf(missing_jvm('1.7'), 'no java 1.7 installation on testing machine')
  def test_java_seven(self):
    self._testjvms('seven')

  @skipIf(missing_jvm('1.6'), 'no java 1.6 installation on testing machine')
  def test_java_six(self):
    self._testjvms('six')

  @skipIf(missing_jvm('1.8'), 'no java 1.8 installation on testing machine')
  def test_with_test_platform(self):
    self._testjvms('eight-test-platform')
