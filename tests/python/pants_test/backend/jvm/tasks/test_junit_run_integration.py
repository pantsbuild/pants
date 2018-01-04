# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import codecs
import os
import time
from unittest import skipIf

from parameterized import parameterized

from pants.base.build_environment import get_buildroot
from pants_test.backend.jvm.tasks.missing_jvm_check import is_missing_jvm
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


OUTPUT_MODES = [('legacy_layout', ['--legacy-report-layout'], True),
                ('nominal_layout', ['--no-legacy-report-layout'], False)]


class JunitRunIntegrationTest(PantsRunIntegrationTest):

  def _testjvms(self, spec_name):
    spec = 'testprojects/tests/java/org/pantsbuild/testproject/testjvms:{}'.format(spec_name)
    self.assert_success(self.run_pants(['clean-all', 'test.junit', '--strict-jvm-version', spec]))

  @skipIf(is_missing_jvm('1.8'), 'no java 1.8 installation on testing machine')
  def test_java_eight(self):
    self._testjvms('eight')

  @skipIf(is_missing_jvm('1.8'), 'no java 1.8 installation on testing machine')
  def test_with_test_platform(self):
    self._testjvms('eight-test-platform')

  def test_junit_run_against_class_succeeds(self):
    pants_run = self.run_pants(['clean-all',
                                'test.junit',
                                '--test=org.pantsbuild.testproject.matcher.MatcherTest',
                                'testprojects/tests/java/org/pantsbuild/testproject/matcher'])
    self.assert_success(pants_run)

  def report_file_path(self, results, relpath, legacy=False):
    return os.path.join(results.workdir if legacy else os.path.join(get_buildroot(), 'dist'),
                        relpath)

  @parameterized.expand(OUTPUT_MODES)
  def test_junit_run_with_cobertura_coverage_succeeds(self, unused_test_name, extra_args, legacy):
    with self.pants_results(['clean-all', 'test.junit'] + extra_args +
                            ['testprojects/tests/java/org/pantsbuild/testproject/unicode::',
                             '--test-junit-coverage-processor=cobertura',
                             '--test-junit-coverage']) as results:
      self.assert_success(results)
      # validate that the expected coverage file exists, and it reflects 100% line rate coverage
      coverage_xml = self.report_file_path(results, 'test/junit/coverage/xml/coverage.xml', legacy)
      self.assertTrue(os.path.isfile(coverage_xml))
      with codecs.open(coverage_xml, 'r', encoding='utf8') as xml:
        self.assertIn('line-rate="1.0"', xml.read())
      # validate that the html report was able to find sources for annotation
      cucumber_src_html = self.report_file_path(
          results,
          'test/junit/coverage/html/'
          'org.pantsbuild.testproject.unicode.cucumber.CucumberAnnotatedExample.html',
          legacy)
      self.assertTrue(os.path.isfile(cucumber_src_html))
      with codecs.open(cucumber_src_html, 'r', encoding='utf8') as src:
        self.assertIn('String pleasantry()', src.read())

  @parameterized.expand(OUTPUT_MODES)
  def test_junit_run_with_jacoco_coverage_succeeds(self, unused_test_name, extra_args, legacy):
    with self.pants_results(['clean-all', 'test.junit'] + extra_args +
                            ['testprojects/tests/java/org/pantsbuild/testproject/unicode::',
                             '--test-junit-coverage-processor=jacoco',
                             '--test-junit-coverage']) as results:
      self.assert_success(results)
      # validate that the expected coverage file exists, and it reflects 100% line rate coverage
      coverage_xml = self.report_file_path(results, 'test/junit/coverage/reports/xml', legacy)
      self.assertTrue(os.path.isfile(coverage_xml))
      with codecs.open(coverage_xml, 'r', encoding='utf8') as xml:
        self.assertIn(
          '<class name="org/pantsbuild/testproject/unicode/cucumber/CucumberAnnotatedExample">'
          '<method name="&lt;init&gt;" desc="()V" line="13">'
          '<counter type="INSTRUCTION" missed="0" covered="3"/>', xml.read())
      # validate that the html report was able to find sources for annotation
      cucumber_src_html = self.report_file_path(
          results,
          'test/junit/coverage/reports/html/'
          'org.pantsbuild.testproject.unicode.cucumber/CucumberAnnotatedExample.html',
          legacy)
      self.assertTrue(os.path.isfile(cucumber_src_html))
      with codecs.open(cucumber_src_html, 'r', encoding='utf8') as src:
        self.assertIn('class="el_method">pleasantry()</a>', src.read())

  def test_junit_run_against_invalid_class_fails(self):
    pants_run = self.run_pants(['clean-all',
                                'test.junit',
                                '--test=org.pantsbuild.testproject.matcher.MatcherTest_BAD_CLASS',
                                'testprojects/tests/java/org/pantsbuild/testproject/matcher'])
    self.assert_failure(pants_run)
    self.assertIn("No target found for test specifier", pants_run.stdout_data)

  def test_junit_run_timeout_succeeds(self):
    sleeping_target = 'testprojects/tests/java/org/pantsbuild/testproject/timeout:sleeping_target'
    pants_run = self.run_pants(['clean-all',
                                'test.junit',
                                '--timeouts',
                                '--timeout-default=1',
                                '--timeout-terminate-wait=1',
                                '--test=org.pantsbuild.testproject.timeout.ShortSleeperTest',
                                sleeping_target])
    self.assert_success(pants_run)

  def test_junit_run_timeout_fails(self):
    sleeping_target = 'testprojects/tests/java/org/pantsbuild/testproject/timeout:sleeping_target'
    start = time.time()
    pants_run = self.run_pants(['clean-all',
                                'test.junit',
                                '--timeouts',
                                '--timeout-default=1',
                                '--timeout-terminate-wait=1',
                                '--test=org.pantsbuild.testproject.timeout.LongSleeperTest',
                                sleeping_target])
    end = time.time()
    self.assert_failure(pants_run)

    # Ensure that the failure took less than 120 seconds to run.
    self.assertLess(end - start, 120)

    # Ensure that the timeout triggered.
    self.assertIn(" timed out after 1 seconds", pants_run.stdout_data)

  def test_junit_tests_using_cucumber(self):
    test_spec = 'testprojects/tests/java/org/pantsbuild/testproject/cucumber'
    with self.pants_results(['clean-all', 'test.junit', '--per-test-timer', test_spec]) as results:
      self.assert_success(results)

  def test_disable_synthetic_jar(self):
    synthetic_jar_target = 'testprojects/tests/java/org/pantsbuild/testproject/syntheticjar:test'
    output = self.run_pants(['test.junit', '--output-mode=ALL', synthetic_jar_target]).stdout_data
    self.assertIn('Synthetic jar run is detected', output)

    output = self.run_pants(['test.junit',
                             '--output-mode=ALL',
                             '--no-jvm-synthetic-classpath',
                             synthetic_jar_target]).stdout_data
    self.assertIn('Synthetic jar run is not detected', output)

  def do_test_junit_run_with_html_report(self, tests=(), args=(), legacy=False):
    def html_report_test(test):
      return '--test=org.pantsbuild.testproject.htmlreport.HtmlReportTest#{}'.format(test)

    with self.pants_results(['clean-all', 'test.junit'] + list(args) +
                            [html_report_test(name) for name in tests] +
                            ['testprojects/tests/java/org/pantsbuild/testproject/htmlreport::',
                             '--test-junit-html-report']) as results:
      self.assert_failure(results)
      report_html = self.report_file_path(results, 'test/junit/reports/junit-report.html', legacy)
      self.assertTrue(os.path.isfile(report_html))
      with codecs.open(report_html, 'r', encoding='utf8') as src:
        html = src.read()
        self.assertIn('testPasses', html)
        self.assertIn('testFails', html)
        self.assertIn('testErrors', html)
        self.assertIn('testSkipped', html)

  @parameterized.expand(OUTPUT_MODES)
  def test_junit_run_with_html_report(self, unused_test_name, extra_args, legacy):
    self.do_test_junit_run_with_html_report(args=extra_args, legacy=legacy)

  @parameterized.expand(OUTPUT_MODES)
  def test_junit_run_with_html_report_merged(self, unused_test_name, extra_args, legacy):
    self.do_test_junit_run_with_html_report(tests=['testPasses',
                                                   'testFails',
                                                   'testErrors',
                                                   'testSkipped'],
                                            args=['--batch-size=3'] + extra_args,
                                            legacy=legacy)
