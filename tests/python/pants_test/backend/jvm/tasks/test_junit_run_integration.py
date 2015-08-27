# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from unittest import skipIf

from pants.java.distribution.distribution import DistributionLocator
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.subsystem.subsystem_util import subsystem_instance


def missing_jvm(version):
  with subsystem_instance(DistributionLocator):
    try:
      DistributionLocator.locate(minimum_version=version, maximum_version='{}.9999'.format(version))
      return False
    except DistributionLocator.Error:
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

  def test_junit_run_against_class_succeeds(self):
    self.assert_success(self.run_pants(['clean-all', 'test.junit', '--test=org.pantsbuild.testproject.matcher.MatcherTest', 'testprojects/tests/java/org/pantsbuild/testproject/matcher']))

  def test_junit_run_against_invalid_class_fails(self):
    pants_run = self.run_pants(['clean-all', 'test.junit', '--test=org.pantsbuild.testproject.matcher.MatcherTest_BAD_CLASS', 'testprojects/tests/java/org/pantsbuild/testproject/matcher'])
    self.assert_failure(pants_run)
    self.assertIn("Unknown target for test", pants_run.stdout_data)
