# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections
import fnmatch
import itertools
import logging
import os
import xml.etree.ElementTree as ET
from abc import abstractmethod
from functools import total_ordering

from pants.base.mustache import MustacheRenderer
from pants.util.dirutil import safe_mkdir_for, safe_walk
from pants.util.memo import memoized_property
from pants.util.meta import AbstractClass
from pants.util.objects import datatype
from pants.util.strutil import ensure_binary


_LOGGER = logging.getLogger(__name__)


@total_ordering
class ReportTestSuite(object):
  """Data object for a JUnit test suite"""

  class MergeError(Exception):
    def __init__(self, suites, test_cases):
      error_message = ('Refusing to merge duplicate test cases in suite {!r} from files {}:'
                       '\n    {}').format(suites[0].name,
                                          ', '.join(s.file for s in suites),
                                          '\n    '.join(map(str, test_cases)))
      super(ReportTestSuite.MergeError, self).__init__(error_message)

  @classmethod
  def merged(cls, report_test_suites, error_on_conflict=True, logger=None):
    """Merges any like-named test suites into one test suite encompasing all the suite's test cases.

    :param report_test_suites: A sequence of test suites to merge results from.
    :type report_test_suites: :class:`collections.Iterable` of :class:`ReportTestSuite`
    :param bool error_on_conflict: `True` to raise when two or more test cases in a given test suite
                                   have the same name; otherwise the conflict is logged and the 1st
                                   encountered duplicate is used.
    :param logger: An optional logger to use for logging merge conflicts.
    :type logger: :class:`logging.Logger`
    :raises: :class:`ReportTestSuite.MergeError` if configured to do so on merge errors.
    :yields: One test suite per unique test suite name in `report_test_suites` with the results of
             all like-named test suites merged.
    :rtype: iter of :class:`ReportTestSuite`
    """

    logger = logger or _LOGGER

    suites_by_name = collections.defaultdict(list)
    for report_test_suite in report_test_suites:
      suites_by_name[report_test_suite.name].append(report_test_suite)

    for suite_name, suites in suites_by_name.items():
      cases_by_name = collections.defaultdict(list)
      for case in itertools.chain.from_iterable(s.testcases for s in suites):
        cases_by_name[case.name].append(case)

      test_cases = []
      tests, errors, failures, skipped, time = 0, 0, 0, 0, 0
      for cases in cases_by_name.values():
        if len(cases) > 1:
          if error_on_conflict:
            raise cls.MergeError(suites, cases)
          else:
            logger.warning('Found duplicate test case results in suite {!r} from files: {}, '
                           'using first result:\n -> {}'.format(suite_name,
                                                                ', '.join(s.file for s in suites),
                                                                '\n    '.join(map(str, cases))))
        case = iter(cases).next()
        tests += 1
        time += case.time
        if case.error:
          errors += 1
        elif case.failure:
          failures += 1
        elif case.skipped:
          skipped += 1
        test_cases.append(case)

      yield cls(name=suite_name,
                tests=tests,
                errors=errors,
                failures=failures,
                skipped=skipped,
                time=time,
                testcases=test_cases)

  def __init__(self, name, tests, errors, failures, skipped, time, testcases, file=None):
    self.name = name
    self.tests = int(tests)
    self.errors = int(errors)
    self.failures = int(failures)
    self.skipped = int(skipped)
    self.time = float(time)
    self.testcases = testcases
    self.file = file

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
      unsuccessful_count = error_count + failure_count + skipped_count
      return '{:.2f}%'.format((test_count - unsuccessful_count) * 100.0 / test_count)
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
    d = dict(name=self.name,
             tests=self.tests,
             errors=self.errors,
             failures=self.failures,
             skipped=self.skipped,
             time=self.time)
    d['success'] = ReportTestSuite.success_rate(self.tests, self.errors, self.failures,
                                                self.skipped)
    d['icon_class'] = ReportTestSuite.icon_class(self.tests, self.errors, self.failures,
                                                 self.skipped)
    d['testcases'] = map(lambda tc: tc.as_dict(), self.testcases)
    return d


class ReportTestCase(datatype('ReportTestCase', ['name', 'time', 'failure', 'error', 'skipped'])):
  """Data object for a JUnit test case"""

  def __new__(cls, name, time, failure=None, error=None, skipped=False):
    return super(ReportTestCase, cls).__new__(cls, name, float(time), failure, error, skipped)

  @memoized_property
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
    d = dict(name=self.name,
             time=self.time,
             icon_class=self.icon_class)
    if self.error:
      d['message'] = self.error
    elif self.failure:
      d['message'] = self.failure
    return d


class JUnitHtmlReportInterface(AbstractClass):
  """The interface JUnit html reporters must support."""

  @abstractmethod
  def report(self, output_dir):
    """Generate the junit test result report

    :returns: The generated report path iff it should be opened for the user.
    :rtype: str
    """


class NoJunitHtmlReport(JUnitHtmlReportInterface):
  """JUnit html reporter that never produces a report."""

  def report(self, output_dir):
    return None


class JUnitHtmlReport(JUnitHtmlReportInterface):
  """Generates an HTML report from JUnit TEST-*.xml files"""

  @classmethod
  def create(cls, xml_dir, open_report=False, logger=None, error_on_conflict=True):
    return cls(xml_dir=xml_dir,
               open_report=open_report,
               logger=logger,
               error_on_conflict=error_on_conflict)

  def __init__(self, xml_dir, open_report=False, logger=None, error_on_conflict=True):
    self._xml_dir = xml_dir
    self._open_report = open_report
    self._logger = logger or _LOGGER
    self._error_on_conflict = error_on_conflict

  def report(self, output_dir):
    self._logger.debug('Generating JUnit HTML report...')
    testsuites = self._parse_xml_files()
    report_file_path = os.path.join(output_dir, 'reports', 'junit-report.html')
    safe_mkdir_for(report_file_path)
    with open(report_file_path, 'wb') as fp:
      fp.write(ensure_binary(self._generate_html(testsuites)))
    self._logger.debug('JUnit HTML report generated to {}'.format(report_file_path))
    if self._open_report:
      return report_file_path

  def _parse_xml_files(self):
    testsuites = []
    for root, dirs, files in safe_walk(self._xml_dir, topdown=True):
      dirs.sort()  # Ensures a consistent gathering order.
      for xml_file in sorted(fnmatch.filter(files, 'TEST-*.xml')):
        testsuites += self._parse_xml_file(os.path.join(root, xml_file))
    merged_suites = ReportTestSuite.merged(testsuites,
                                           logger=self._logger,
                                           error_on_conflict=self._error_on_conflict)
    return sorted(merged_suites)

  @staticmethod
  def _parse_xml_file(xml_file):
    testsuites = []
    root = ET.parse(xml_file).getroot()

    testcases = []
    for testcase in root.iter('testcase'):
      failure = None
      for f in testcase.iter('failure'):
        failure = f.text
      error = None
      for e in testcase.iter('error'):
        error = e.text
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
        testcases,
        file=xml_file,
      ))
    return testsuites

  @staticmethod
  def _generate_html(testsuites):
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
