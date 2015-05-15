# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import time
import unittest

from mock import Mock, call

from pants.base.workunit import WorkUnit
from pants.reporting.report import Report
from pants.reporting.reporter import Reporter
from pants.util.contextutil import temporary_dir


def raise_keyboard_interrupt():
  raise KeyboardInterrupt()


def raise_exception():
  raise Exception()


class MockReporter(Reporter):
  def __init__(self):
    super(MockReporter, self).__init__(None, None)
    self.open = Mock()
    self.close = Mock()
    self.start_workunit = Mock()
    self.end_workunit = Mock()
    self.handle_log = Mock()
    self.handle_output = Mock()


class ReportTest(unittest.TestCase):
  def setUp(self):
    super(ReportTest, self).setUp()
    self.mock_reporter = MockReporter()
    self.report = Report()
    self.report.add_reporter('mock', self.mock_reporter)

  def run_all(self):
    while not self.report._work_queue.empty():
      self.report._work_queue.get_nowait()()

  def test_notifying_reports_on_workunit_start(self):
    with temporary_dir() as temp_dir:
      workunit = WorkUnit(temp_dir, None, 'work')

      self.report.start_workunit(workunit)
      self.run_all()

      self.mock_reporter.start_workunit.assert_called_with(workunit)

  def test_starting_already_started_workunit(self):
    with temporary_dir() as temp_dir:
      workunit = WorkUnit(temp_dir, None, 'work')
      self.report.start_workunit(workunit)

      self.report.start_workunit(workunit)
      self.run_all()

      self.mock_reporter.start_workunit.assert_called_once_with(workunit)

  def test_notifying_reports_on_workunit_end(self):
    with temporary_dir() as temp_dir:
      workunit = WorkUnit(temp_dir, None, 'work')

      self.report.start_workunit(workunit)
      self.report.end_workunit(workunit)
      self.run_all()

      self.mock_reporter.end_workunit.assert_called_with(workunit)

  def test_ending_workunit_with_remaining_unconsumed_output_notifies_about_output(self):
    with temporary_dir() as temp_dir:
      workunit = WorkUnit(temp_dir, None, 'work')

      self.report.start_workunit(workunit)
      workunit.output('someout').write('abc')

      self.report.end_workunit(workunit)
      self.run_all()

      self.mock_reporter.handle_output.assert_called_with(workunit, 'someout', 'abc')

  def test_ending_already_ended_workunit(self):
    with temporary_dir() as temp_dir:
      workunit = WorkUnit(temp_dir, None, 'work')
      self.report.start_workunit(workunit)

      self.report.end_workunit(workunit)
      self.report.end_workunit(workunit)
      self.run_all()

      self.mock_reporter.end_workunit.assert_called_once_with(workunit)

  def test_multiple_workunits_with_output_when_output_notified(self):
    with temporary_dir() as temp_dir:
      workunit_a = WorkUnit(temp_dir, None, 'a')
      workunit_b = WorkUnit(temp_dir, None, 'b')
      self.report.start_workunit(workunit_a)
      self.report.start_workunit(workunit_b)
      workunit_a.output('someout').write('abc')
      workunit_b.output('someout').write('abc')

      self.report.flush_output()
      self.run_all()

      self.mock_reporter.handle_output.assert_has_calls([call(workunit_a, 'someout', 'abc'),
                                                         call(workunit_b, 'someout', 'abc')],
                                                        any_order=True)

  def test_keyboard_interrupts_raised_on_main_thread_from_reporters_open(self):
    mock_reporter = MockReporter()
    mock_reporter.open.side_effect = raise_keyboard_interrupt

    report = Report()
    report.add_reporter('mock', mock_reporter)

    with self.assertRaises(KeyboardInterrupt):
      try:
        report.open()
        time.sleep(2)
      finally:
        report.close()

  def test_exception_on_report_thread_interrupts_main_thread(self):
    mock_reporter = MockReporter()
    mock_reporter.open.side_effect = raise_exception

    report = Report()
    report.add_reporter('mock', mock_reporter)

    with self.assertRaises(KeyboardInterrupt):
      try:
        report.open()
        time.sleep(2)
      finally:
        report.close()

  def test_keyboard_interrupts_raised_on_main_thread_from_watcher_thread_via_flush(self):
    report = Report()
    report.flush_output = Mock(side_effect=raise_keyboard_interrupt)

    with self.assertRaises(KeyboardInterrupt):
      try:
        report.open()
        time.sleep(2)
      finally:
        report.close()
