# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import glob
import os
import xml.etree.ElementTree as ET
from functools import total_ordering

from pants.base.mustache import MustacheRenderer
from pants.util.dirutil import safe_mkdir
from pants.util.meta import AbstractClass
from pants.util.strutil import ensure_binary


@total_ordering
class ReportTestSuite(object):
  """Data object for a JUnit test suite"""

  def __init__(self, name, tests, errors, failures, skipped, time, testcases):
    self.name = name
    self.tests = int(tests)
    self.errors = int(errors)
    self.failures = int(failures)
    self.skipped = int(skipped)
    self.time = float(time)
    self.testcases = testcases

  def __lt__(self, other):
    if (self.errors, self.failures) > (other.errors, other.failures):
      return True
    elif (self.errors, self.failures) < (other.errors, other.failures):
      return False
    else:
      return self.name.lower() < other.name.lower()

  @staticmethod
  def success_rate(test_count, error_count, failure_count, skipped_count):
    if test_count:
      return '{:.2f}%'.format((test_count - (error_count + failure_count + skipped_count)) * 100.0 / test_count)
    return '0.00%'

  @staticmethod
  def icon_class(test_count, error_count, failure_count, skipped_count):
    icon_class = 'test-passed'
    if test_count == skipped_count:
      icon_class = 'test-skipped'
    elif error_count > 0:
      icon_class = 'test-error'
    elif failure_count > 0:
      icon_class = 'test-failure'
    return icon_class

  def as_dict(self):
    d = self.__dict__
    d['success'] = ReportTestSuite.success_rate(self.tests, self.errors, self.failures, self.skipped)
    d['icon_class'] = ReportTestSuite.icon_class(self.tests, self.errors, self.failures, self.skipped)
    d['testcases'] = map(lambda tc: tc.as_dict(), self.testcases)
    return d


class ReportTestCase(object):
  """Data object for a JUnit test case"""

  def __init__(self, name, time, failure, error, skipped):
    self.name = name
    self.time = float(time)
    self.failure = failure
    self.error = error
    self.skipped = skipped

  def icon_class(self):
    icon_class = 'test-passed'
    if self.skipped:
      icon_class = 'test-skipped'
    elif self.error:
      icon_class = 'test-error'
    elif self.failure:
      icon_class = 'test-failure'
    return icon_class

  def as_dict(self):
    d = {}
    d['name'] = self.name
    d['time'] = self.time
    d['icon_class'] = self.icon_class()
    if self.error:
      d['message'] = self.error['message']
    elif self.failure:
      d['message'] = self.failure['message']
    return d


class JUnitHtmlReport(AbstractClass):
  """Generates an HTML report from JUnit TEST-*.xml files"""

  def report(self, xml_dir, report_dir):
    testsuites = self.parse_xml_files(xml_dir)
    safe_mkdir(report_dir)
    report_file_path = os.path.join(report_dir, 'junit-report.html')
    with open(report_file_path, 'w') as fp:
      fp.write(ensure_binary(self.generate_html(testsuites)))
    return report_file_path

  def parse_xml_files(self, xml_dir):
    testsuites = []
    for xml_file in glob.glob(os.path.join(xml_dir, 'TEST-*.xml')):
      testsuites += self.parse_xml_file(xml_file)
    testsuites.sort()
    return testsuites

  def parse_xml_file(self, xml_file):
    testsuites = []
    root = ET.parse(xml_file).getroot()

    testcases = []
    for testcase in root.iter('testcase'):
      failure = None
      for f in testcase.iter('failure'):
        failure = {
          'type': f.attrib['type'],
          'message': f.text
        }
      error = None
      for e in testcase.iter('error'):
        error = {
          'type': e.attrib['type'],
          'message': e.text
        }
      skipped = False
      for _s in testcase.iter('skipped'):
        skipped = True

      testcases.append(ReportTestCase(
        testcase.attrib['name'],
        testcase.attrib.get('time', 0),
        failure,
        error,
        skipped
      ))

    for testsuite in root.iter('testsuite'):
      testsuites.append(ReportTestSuite(
        testsuite.attrib['name'],
        testsuite.attrib['tests'],
        testsuite.attrib['errors'],
        testsuite.attrib['failures'],
        testsuite.attrib.get('skipped', 0),
        testsuite.attrib['time'],
        testcases
      ))
    return testsuites

  def generate_html(self, testsuites):
    values = {
      'total_tests': 0,
      'total_errors': 0,
      'total_failures': 0,
      'total_skipped': 0,
      'total_time': 0.0
    }

    for testsuite in testsuites:
      values['total_tests'] += testsuite.tests
      values['total_errors'] += testsuite.errors
      values['total_failures'] += testsuite.failures
      values['total_skipped'] += testsuite.skipped
      values['total_time'] += testsuite.time

    values['total_success'] = ReportTestSuite.success_rate(values['total_tests'],
                                                           values['total_errors'],
                                                           values['total_failures'],
                                                           values['total_skipped'])
    values['summary_icon_class'] = ReportTestSuite.icon_class(values['total_tests'],
                                                              values['total_errors'],
                                                              values['total_failures'],
                                                              values['total_skipped'])
    values['testsuites'] = map(lambda ts: ts.as_dict(), testsuites)

    package_name, _, _ = __name__.rpartition('.')
    renderer = MustacheRenderer(package_name=package_name)
    html = renderer.render_name('junit_report.html', values)
    return html
