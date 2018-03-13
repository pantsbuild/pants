# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pants.backend.jvm.tasks.reports.junit_html_report import (JUnitHtmlReport, ReportTestCase,
                                                               ReportTestSuite)
from pants.util.contextutil import temporary_dir
from pants.util.strutil import ensure_text
from pants_test.base_test import BaseTest


class TestJUnitHtmlReport(BaseTest):

  _JUNIT_XML_DIR = 'tests/python/pants_test/backend/jvm/tasks/reports/junit_xml'

  def parse_xml_file(self, basename):
    xml_file_path = os.path.join(self._JUNIT_XML_DIR, basename)
    return JUnitHtmlReport._parse_xml_file(xml_file_path)

  def test_passing(self):
    testsuites = self.parse_xml_file('pass/TEST-org.pantsbuild.PassingTest.xml')
    self.assertEqual(1, len(testsuites))
    self.assertEqual(4, testsuites[0].tests)
    self.assertEqual(0, testsuites[0].errors)
    self.assertEqual(0, testsuites[0].failures)
    self.assertEqual(0, testsuites[0].skipped)
    self.assertEqual(4.76, testsuites[0].time)
    self.assertEqual(4, len(testsuites[0].testcases))
    self.assertIsNone(testsuites[0].testcases[0].failure)
    self.assertIsNone(testsuites[0].testcases[0].error)

  def test_failed(self):
    testsuites = self.parse_xml_file('fail/TEST-org.pantsbuild.FailureTest.xml')
    self.assertEqual(1, len(testsuites))
    self.assertEqual(1, testsuites[0].tests)
    self.assertEqual(0, testsuites[0].errors)
    self.assertEqual(1, testsuites[0].failures)
    self.assertEqual(0, testsuites[0].skipped)
    self.assertEqual(0.01, testsuites[0].time)
    self.assertEqual(1, len(testsuites[0].testcases))
    self.assertIsNone(testsuites[0].testcases[0].error)
    self.assertIn('java.lang.AssertionError', testsuites[0].testcases[0].failure)

  def test_errored(self):
    testsuites = self.parse_xml_file('error/TEST-org.pantsbuild.ErrorTest.xml')
    self.assertEqual(1, len(testsuites))
    self.assertEqual(1, testsuites[0].tests)
    self.assertEqual(1, testsuites[0].errors)
    self.assertEqual(0, testsuites[0].failures)
    self.assertEqual(0, testsuites[0].skipped)
    self.assertEqual(0.32, testsuites[0].time)
    self.assertEqual(1, len(testsuites[0].testcases))
    self.assertIsNone(testsuites[0].testcases[0].failure)
    self.assertIn('java.lang.RuntimeException', testsuites[0].testcases[0].error)

  def test_skipped(self):
    testsuites = self.parse_xml_file('skip/TEST-org.pantsbuild.SkippedTest.xml')
    self.assertEqual(1, len(testsuites))
    self.assertEqual(1, testsuites[0].tests)
    self.assertEqual(0, testsuites[0].errors)
    self.assertEqual(0, testsuites[0].failures)
    self.assertEqual(1, testsuites[0].skipped)
    self.assertEqual(0, testsuites[0].time)
    self.assertEqual(1, len(testsuites[0].testcases))

  def test_time(self):
    testsuites = self.parse_xml_file('time/TEST-org.pantsbuild.TimeTest.xml')
    self.assertEqual(1, len(testsuites))
    self.assertEqual(4, testsuites[0].tests)
    self.assertEqual(0.5, testsuites[0].time)
    self.assertEqual(4, len(testsuites[0].testcases))

  def test_empty(self):
    testsuites = self.parse_xml_file('empty/TEST-org.pantsbuild.EmptyTestSuite.xml')
    self.assertEqual(1, len(testsuites))
    self.assertEqual(0, len(testsuites[0].testcases))

  def test_unicode(self):
    testsuites = self.parse_xml_file('unicode/TEST-org.pantsbuild.UnicodeCharsTest.xml')
    self.assertEqual(1, len(testsuites))
    self.assertEqual(2, testsuites[0].tests)
    self.assertEqual(2, len(testsuites[0].testcases))
    self.assertEquals(u'org.pantsbuild.PåssingTest', testsuites[0].name)
    self.assertEquals(u'testTwö', testsuites[0].testcases[1].name)
    self.assertIn(u'org.pantsbuild.PåssingTest.testTwö', testsuites[0].testcases[1].error)

  def test_open_report(self):
    with temporary_dir() as output_dir:
      junit_html_report = JUnitHtmlReport.create(xml_dir=self._JUNIT_XML_DIR, open_report=True)
      report_file_path = junit_html_report.report(output_dir)
      self.assertIsNotNone(report_file_path)
      stat = os.stat(report_file_path)
      self.assertGreater(stat.st_size, 0)

  def test_no_open_report(self):
    with temporary_dir() as output_dir:
      junit_html_report = JUnitHtmlReport.create(xml_dir=self._JUNIT_XML_DIR, open_report=False)
      report_file_path = junit_html_report.report(output_dir)
      self.assertIsNone(report_file_path)

  def test_all(self):
    testsuites = JUnitHtmlReport.create(self._JUNIT_XML_DIR)._parse_xml_files()
    self.assertEqual(7, len(testsuites))

    with temporary_dir() as output_dir:
      junit_html_report = JUnitHtmlReport.create(xml_dir=self._JUNIT_XML_DIR, open_report=True)
      with open(junit_html_report.report(output_dir)) as html_file:
        html_data = ensure_text(html_file.read())
        self.assertIn(u'</span>&nbsp;org.pantsbuild.PåssingTest', html_data)
        self.assertIn(u'</span>&nbsp;testTwö</td>', html_data)
        self.assertIn(u'at org.pantsbuild.PåssingTest.testTwö(ErrorTest.java:29)', html_data)

  def test_merged_no_conflict(self):
    with temporary_dir() as xml_dir:
      def write_xml(name, xml, path=''):
        with open(os.path.join(xml_dir, path, 'TEST-{}.xml'.format(name)), 'wb') as fp:
          fp.write(xml)

      write_xml('a-1', """
      <testsuite name="suite-a" errors="0" failures="0" skipped="0" tests="1" time="0.01">
        <testcase name="test-a" time="0.01" />
      </testsuite>
      """)

      write_xml('a-2', """
      <testsuite name="suite-a" errors="0" failures="0" skipped="0" tests="1" time="0.01">
        <testcase name="test-b" time="0.01" />
      </testsuite>
      """)

      write_xml('b', """
      <testsuite name="suite-b" errors="0" failures="0" skipped="0" tests="2" time="0.04">
        <testcase name="test-a" time="0.01" />
        <testcase name="test-b" time="0.03" />
      </testsuite>
      """)

      testsuites = list(ReportTestSuite.merged(JUnitHtmlReport.create(xml_dir)._parse_xml_files()))
      self.assertEqual(2, len(testsuites))

      suites_by_name = {suite.name: suite for suite in testsuites}
      self.assertEqual(2, len(suites_by_name))

      suite_a = suites_by_name['suite-a']
      self.assertEqual(0, suite_a.errors)
      self.assertEqual(0, suite_a.failures)
      self.assertEqual(0, suite_a.skipped)
      self.assertEqual(0.02, suite_a.time)
      self.assertEqual(2, suite_a.tests)
      self.assertEqual(2, len(suite_a.testcases))

      suite_b = suites_by_name['suite-b']
      self.assertEqual(0, suite_b.errors)
      self.assertEqual(0, suite_b.failures)
      self.assertEqual(0, suite_b.skipped)
      self.assertEqual(0.04, suite_b.time)
      self.assertEqual(2, suite_b.tests)
      self.assertEqual(2, len(suite_b.testcases))

  @contextmanager
  def merge_conflict(self):
    with temporary_dir() as xml_dir:
      def write_xml(name, xml, path=''):
        with open(os.path.join(xml_dir, path, 'TEST-{}.xml'.format(name)), 'wb') as fp:
          fp.write(xml)

      write_xml('a-1', """
      <testsuite name="suite-a" errors="0" failures="0" skipped="0" tests="1" time="0.02">
        <testcase name="test-a" time="0.02" />
      </testsuite>
      """)

      write_xml('a-2', """
      <testsuite name="suite-a" errors="1" failures="0" skipped="1" tests="2" time="0.03">
        <testcase name="test-a" time="0.01" />
        <testcase name="test-b" time="0.02">
          <error type="java.lang.RuntimeException">java.lang.RuntimeException!</error>
        </testcase>
      </testsuite>
      """)

      yield xml_dir

  def test_merged_conflict_error(self):
    with self.merge_conflict() as xml_dir:
      report = JUnitHtmlReport.create(xml_dir, error_on_conflict=True)
      with self.assertRaises(ReportTestSuite.MergeError):
        report._parse_xml_files()

  def test_merged_conflict_first(self):
    with self.merge_conflict() as xml_dir:
      report = JUnitHtmlReport.create(xml_dir, error_on_conflict=False)

      testsuites = report._parse_xml_files()
      self.assertEqual(1, len(testsuites))

      suite_a = testsuites[0]
      self.assertEqual(1, suite_a.errors)
      self.assertEqual(0, suite_a.failures)
      self.assertEqual(0, suite_a.skipped)
      self.assertEqual(0.04, suite_a.time)
      self.assertEqual(2, suite_a.tests)
      self.assertEqual([ReportTestCase(name='test-a', time=0.02),
                        ReportTestCase(name='test-b', time=0.02,
                                       error='java.lang.RuntimeException!')],
                       suite_a.testcases)
