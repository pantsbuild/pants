# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sys

from six import StringIO

from pants.base.workunit import WorkUnitLabel
from pants.option.custom_types import dict_option, list_option
from pants.reporting.html_reporter import HtmlReporter
from pants.reporting.invalidation_report import InvalidationReport
from pants.reporting.plaintext_reporter import LabelFormat, PlainTextReporter, ToolOutputFormat
from pants.reporting.quiet_reporter import QuietReporter
from pants.reporting.report import Report, ReportingError
from pants.reporting.reporting_server import ReportingServerManager
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import relative_symlink, safe_mkdir, safe_rmtree


class Reporting(Subsystem):
  options_scope = 'reporting'

  @classmethod
  def register_options(cls, register):
    super(Reporting, cls).register_options(register)
    register('--invalidation-report', default=False, action='store_true',
             help='Write a formatted report on the invalid objects to the specified path.')
    register('--reports-dir', advanced=True, metavar='<dir>',
             default=os.path.join(register.bootstrap.pants_workdir, 'reports'),
             help='Write reports to this dir.')
    register('--template-dir', advanced=True, metavar='<dir>', default=None,
             help='Find templates for rendering in this dir.')
    register('--console-label-format', advanced=True, type=dict_option,
             default=PlainTextReporter.LABEL_FORMATTING,
             help='Controls the printing of workunit labels to the console.  Workunit types are '
                  '{workunits}.  Possible formatting values are {formats}'.format(
               workunits=WorkUnitLabel.keys(), formats=LabelFormat.keys()))
    register('--console-tool-output-format', advanced=True, type=dict_option,
             default=PlainTextReporter.TOOL_OUTPUT_FORMATTING,
             help='Controls the printing of workunit tool output to the console. Workunit types are '
                  '{workunits}.  Possible formatting values are {formats}'.format(
               workunits=WorkUnitLabel.keys(), formats=ToolOutputFormat.keys()))

  def initial_reporting(self, run_tracker):
    """Sets up the initial reporting configuration.

    Will be changed after we parse cmd-line flags.
    """
    link_to_latest = os.path.join(self.get_options().reports_dir, 'latest')

    run_id = run_tracker.run_info.get_info('id')
    if run_id is None:
      raise ReportingError('No run_id set')
    run_dir = os.path.join(self.get_options().reports_dir, run_id)
    safe_rmtree(run_dir)

    html_dir = os.path.join(run_dir, 'html')
    safe_mkdir(html_dir)

    relative_symlink(run_dir, link_to_latest)

    report = Report()

    # Capture initial console reporting into a buffer. We'll do something with it once
    # we know what the cmd-line flag settings are.
    outfile = StringIO()
    capturing_reporter_settings = PlainTextReporter.Settings(
      outfile=outfile, log_level=Report.INFO,
      color=False, indent=True, timing=False,
      cache_stats=False,
      label_format=self.get_options().console_label_format,
      tool_output_format=self.get_options().console_tool_output_format)
    capturing_reporter = PlainTextReporter(run_tracker, capturing_reporter_settings)
    report.add_reporter('capturing', capturing_reporter)

    # Set up HTML reporting. We always want that.
    html_reporter_settings = HtmlReporter.Settings(log_level=Report.INFO,
                                                   html_dir=html_dir,
                                                   template_dir=self.get_options().template_dir)
    html_reporter = HtmlReporter(run_tracker, html_reporter_settings)
    report.add_reporter('html', html_reporter)

    # Add some useful RunInfo.
    run_tracker.run_info.add_info('default_report', html_reporter.report_path())
    port = ReportingServerManager().socket
    if port:
      run_tracker.run_info.add_info('report_url', 'http://localhost:{}/run/{}'.format(port, run_id))

    return report

  def _get_invalidation_report(self):
    return InvalidationReport() if self.get_options().invalidation_report else None

  def update_reporting(self, global_options, is_quiet_task, run_tracker):
    """Updates reporting config once we've parsed cmd-line flags."""

    # Get any output silently buffered in the old console reporter, and remove it.
    old_outfile = run_tracker.report.remove_reporter('capturing').settings.outfile
    old_outfile.flush()
    buffered_output = old_outfile.getvalue()
    old_outfile.close()

    log_level = Report.log_level_from_string(global_options.level or 'info')
    # Ideally, we'd use terminfo or somesuch to discover whether a
    # terminal truly supports color, but most that don't set TERM=dumb.
    color = global_options.colors and (os.getenv('TERM') != 'dumb')
    timing = global_options.time
    cache_stats = global_options.time  # TODO: Separate flag for this?

    if global_options.quiet or is_quiet_task:
      console_reporter = QuietReporter(run_tracker,
                                       QuietReporter.Settings(log_level=log_level, color=color))
    else:
      # Set up the new console reporter.
      settings = PlainTextReporter.Settings(log_level=log_level, outfile=sys.stdout, color=color,
                                            indent=True, timing=timing, cache_stats=cache_stats,
                                            label_format=self.get_options().console_label_format,
                                            tool_output_format=self.get_options().console_tool_output_format)
      console_reporter = PlainTextReporter(run_tracker, settings)
      console_reporter.emit(buffered_output)
      console_reporter.flush()
    run_tracker.report.add_reporter('console', console_reporter)

    if global_options.logdir:
      # Also write plaintext logs to a file. This is completely separate from the html reports.
      safe_mkdir(global_options.logdir)
      run_id = run_tracker.run_info.get_info('id')
      outfile = open(os.path.join(global_options.logdir, '{}.log'.format(run_id)), 'w')
      settings = PlainTextReporter.Settings(log_level=log_level, outfile=outfile, color=False,
                                            indent=True, timing=True, cache_stats=True,
                                            label_format=self.get_options().console_label_format,
                                            tool_output_format=self.get_options().console_tool_output_format)
      logfile_reporter = PlainTextReporter(run_tracker, settings)
      logfile_reporter.emit(buffered_output)
      logfile_reporter.flush()
      run_tracker.report.add_reporter('logfile', logfile_reporter)

    invalidation_report = self._get_invalidation_report()
    if invalidation_report:
      run_id = run_tracker.run_info.get_info('id')
      outfile = os.path.join(self.get_options().reports_dir, run_id, 'invalidation-report.csv')
      invalidation_report.set_filename(outfile)

    return invalidation_report
