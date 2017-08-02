# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from mock import mock

from pants.backend.jvm.tasks.reports.junit_html_report import JUnitHtmlReport
from pants.util.contextutil import temporary_dir
from pants.util.strutil import ensure_text
from pants_test.base_test import BaseTest


class TestJUnitHtmlReport(BaseTest):

  def xml_file_path(self, file):
    return

  def parse_xml_file(self, basename):
    xml_file_path = os.path.join(
      self.real_build_root,
      'tests/python/pants_test/backend/jvm/tasks/reports/junit_html_report_resources',
      basename
    )
    return JUnitHtmlReport._parse_xml_file(xml_file_path)

  def test_passing(self):
    testsuites = self.parse_xml_file('TEST-org.pantsbuild.PassingTest.xml')
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
    testsuites = self.parse_xml_file('TEST-org.pantsbuild.FailureTest.xml')
    self.assertEqual(1, len(testsuites))
    self.assertEqual(1, testsuites[0].tests)
    self.assertEqual(0, testsuites[0].errors)
    self.assertEqual(1, testsuites[0].failures)
    self.assertEqual(0, testsuites[0].skipped)
    self.assertEqual(0.01, testsuites[0].time)
    self.assertEqual(1, len(testsuites[0].testcases))
    self.assertIsNone(testsuites[0].testcases[0].error)
    self.assertEquals('java.lang.AssertionError', testsuites[0].testcases[0].failure['type'])
    self.assertIn('java.lang.AssertionError', testsuites[0].testcases[0].failure['message'])

  def test_errored(self):
    testsuites = self.parse_xml_file('TEST-org.pantsbuild.ErrorTest.xml')
    self.assertEqual(1, len(testsuites))
    self.assertEqual(1, testsuites[0].tests)
    self.assertEqual(1, testsuites[0].errors)
    self.assertEqual(0, testsuites[0].failures)
    self.assertEqual(0, testsuites[0].skipped)
    self.assertEqual(0.32, testsuites[0].time)
    self.assertEqual(1, len(testsuites[0].testcases))
    self.assertIsNone(testsuites[0].testcases[0].failure)
    self.assertEquals('java.lang.RuntimeException', testsuites[0].testcases[0].error['type'])
    self.assertIn('java.lang.RuntimeException', testsuites[0].testcases[0].error['message'])

  def test_skipped(self):
    testsuites = self.parse_xml_file('TEST-org.pantsbuild.SkippedTest.xml')
    self.assertEqual(1, len(testsuites))
    self.assertEqual(1, testsuites[0].tests)
    self.assertEqual(0, testsuites[0].errors)
    self.assertEqual(0, testsuites[0].failures)
    self.assertEqual(1, testsuites[0].skipped)
    self.assertEqual(0, testsuites[0].time)
    self.assertEqual(1, len(testsuites[0].testcases))

  def test_time(self):
    testsuites = self.parse_xml_file('TEST-org.pantsbuild.TimeTest.xml')
    self.assertEqual(1, len(testsuites))
    self.assertEqual(4, testsuites[0].tests)
    self.assertEqual(0.5, testsuites[0].time)
    self.assertEqual(4, len(testsuites[0].testcases))

  def test_empty(self):
    testsuites = self.parse_xml_file('TEST-org.pantsbuild.EmptyTestSuite.xml')
    self.assertEqual(1, len(testsuites))
    self.assertEqual(0, len(testsuites[0].testcases))

  def test_unicode(self):
    testsuites = self.parse_xml_file('TEST-org.pantsbuild.UnicodeCharsTest.xml')
    self.assertEqual(1, len(testsuites))
    self.assertEqual(2, testsuites[0].tests)
    self.assertEqual(2, len(testsuites[0].testcases))
    self.assertEquals(u'org.pantsbuild.PåssingTest', testsuites[0].name)
    self.assertEquals(u'testTwö', testsuites[0].testcases[1].name)
    self.assertIn(u'org.pantsbuild.PåssingTest.testTwö',
                  testsuites[0].testcases[1].error['message'])

  def test_all(self):
    test_dir = os.path.join(
      self.real_build_root,
      'tests/python/pants_test/backend/jvm/tasks/reports/junit_html_report_resources'
    )
    testsuites = JUnitHtmlReport._parse_xml_files(test_dir)
    self.assertEqual(7, len(testsuites))

    with temporary_dir() as output_dir:
      output_file = os.path.join(output_dir, 'junit-report.html')
      JUnitHtmlReport(xml_dir=test_dir, report_dir=output_dir, logger=mock.Mock()).report()
      self.assertTrue(os.path.exists(output_file))
      with open(output_file) as html_file:
        html_data = ensure_text(html_file.read())
        self.assertIn(u'</span>&nbsp;org.pantsbuild.PåssingTest', html_data)
        self.assertIn(u'</span>&nbsp;testTwö</td>', html_data)
        self.assertIn(u'at org.pantsbuild.PåssingTest.testTwö(ErrorTest.java:29)', html_data)
