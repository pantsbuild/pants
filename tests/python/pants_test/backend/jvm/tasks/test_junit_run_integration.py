# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import codecs
import os.path
import time
from unittest import expectedFailure, skipIf

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

  def test_junit_run_with_cobertura_coverage_succeeds(self):
    with self.pants_results(['clean-all', 'test.junit', 'testprojects/tests/java/org/pantsbuild/testproject/unicode::', '--test-junit-coverage-processor=cobertura', '--test-junit-coverage']) as results:
      self.assert_success(results)
      # validate that the expected coverage file exists, and it reflects 100% line rate coverage
      coverage_xml = os.path.join(results.workdir, 'test/junit/coverage/xml/coverage.xml')
      self.assertTrue(os.path.isfile(coverage_xml))
      with codecs.open(coverage_xml, 'r', encoding='utf8') as xml:
        self.assertIn('line-rate="1.0"', xml.read())
      # validate that the html report was able to find sources for annotation
      cucumber_src_html = os.path.join(results.workdir, 'test/junit/coverage/html/org.pantsbuild.testproject.unicode.cucumber.CucumberAnnotatedExample.html')
      self.assertTrue(os.path.isfile(cucumber_src_html))
      with codecs.open(cucumber_src_html, 'r', encoding='utf8') as src:
        self.assertIn('String pleasantry()', src.read())

  def test_junit_run_against_invalid_class_fails(self):
    pants_run = self.run_pants(['clean-all', 'test.junit', '--test=org.pantsbuild.testproject.matcher.MatcherTest_BAD_CLASS', 'testprojects/tests/java/org/pantsbuild/testproject/matcher'])
    self.assert_failure(pants_run)
    self.assertIn("No target found for test specifier", pants_run.stdout_data)

  def test_junit_run_timeout_succeeds(self):
    pants_run = self.run_pants(['clean-all',
                                'test.junit',
                                '--timeout-default=1',
                                '--test=org.pantsbuild.testproject.timeout.SleeperTestShort',
                                'testprojects/tests/java/org/pantsbuild/testproject/timeout:sleeping_target'])
    self.assert_success(pants_run)

  def test_junit_run_timeout_fails(self):
    start = time.time()
    pants_run = self.run_pants(['clean-all',
                                'test.junit',
                                '--timeout-default=1',
                                '--test=org.pantsbuild.testproject.timeout.SleeperTestLong',
                                'testprojects/tests/java/org/pantsbuild/testproject/timeout:sleeping_target'])
    end = time.time()
    self.assert_failure(pants_run)

    # Ensure that the failure took less than 120 seconds to run.
    self.assertLess(end - start, 120)

    # Ensure that the timeout triggered.
    self.assertIn("FAILURE: Timeout of 1 seconds reached", pants_run.stdout_data)

  @expectedFailure
  def test_junit_tests_using_cucumber(self):
    test_spec = 'testprojects/tests/java/org/pantsbuild/testproject/cucumber'
    with self.pants_results(['clean-all', 'test.junit', '--per-test-timer', test_spec]) as results:
      self.assert_success(results)
