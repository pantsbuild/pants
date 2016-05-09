# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.goal.run_tracker import RunTracker
from pants.reporting.report import Report
from pants.reporting.reporting import Reporting


class ReportingInitializer(object):
  """Starts and provides logged info on the RunTracker and Reporting subsystems."""

  def __init__(self, run_tracker=None, reporting=None):
    self._run_tracker = run_tracker or RunTracker.global_instance()
    self._reporting = reporting or Reporting.global_instance()

  def setup(self):
    """Start up the RunTracker and log reporting details."""
    report = self._reporting.initial_reporting(self._run_tracker)
    self._run_tracker.start(report)

    url = self._run_tracker.run_info.get_info('report_url')
    if url:
      self._run_tracker.log(Report.INFO, 'See a report at: {}'.format(url))
    else:
      self._run_tracker.log(Report.INFO, '(To run a reporting server: ./pants server)')

    return self._run_tracker, self._reporting
