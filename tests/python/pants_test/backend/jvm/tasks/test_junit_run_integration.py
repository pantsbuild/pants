# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import codecs
import os.path
import time
from unittest import expectedFailure, skipIf

from pants_test.backend.jvm.tasks.missing_jvm_check import is_missing_jvm
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class JunitRunIntegrationTest(PantsRunIntegrationTest):

  def _testjvms(self, spec_name):
    spec = 'testprojects/tests/java/org/pantsbuild/testproject/testjvms:{}'.format(spec_name)
    self.assert_success(self.run_pants(['clean-all', 'test.junit', '--strict-jvm-version', spec]))

  # See https://github.com/pantsbuild/pants/issues/2894 for details on why this is
  # marked xfail.
  @expectedFailure
  @skipIf(is_missing_jvm('1.8'), 'no java 1.8 installation on testing machine')
  def test_java_eight(self):
    self._testjvms('eight')

  @skipIf(is_missing_jvm('1.7'), 'no java 1.7 installation on testing machine')
  def test_java_seven(self):
    self._testjvms('seven')

  @skipIf(is_missing_jvm('1.6'), 'no java 1.6 installation on testing machine')
  def test_java_six(self):
    self._testjvms('six')

  @skipIf(is_missing_jvm('1.8'), 'no java 1.8 installation on testing machine')
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

  def test_disable_synthetic_jar(self):
    output = self.run_pants(
      ['test.junit',
       '--output-mode=ALL',
       'testprojects/tests/java/org/pantsbuild/testproject/syntheticjar:test']).stdout_data
    self.assertIn('Synthetic jar run is detected', output)

    output = self.run_pants(
      ['test.junit',
        '--output-mode=ALL',
       '--no-jvm-synthetic-classpath',
       'testprojects/tests/java/org/pantsbuild/testproject/syntheticjar:test']).stdout_data
    self.assertIn('Synthetic jar run is not detected', output)

  def test_junit_run_with_html_report(self):
    with self.pants_results(['clean-all', 'test.junit', 'testprojects/tests/java/org/pantsbuild/testproject/htmlreport::', '--test-junit-html-report']) as results:
      self.assert_failure(results)
      report_html = os.path.join(results.workdir, 'test/junit/reports/junit-report.html')
      self.assertTrue(os.path.isfile(report_html))
      with codecs.open(report_html, 'r', encoding='utf8') as src:
        html = src.read()
        self.assertIn('testPasses', html)
        self.assertIn('testFails', html)
        self.assertIn('testErrors', html)
        self.assertIn('testSkipped', html)
