import os
import sys

from twitter.common.dirutil import safe_mkdir, safe_rmtree
from twitter.common.lang import Compatibility

from twitter.pants.reporting.plaintext_reporter import PlainTextReporter
from twitter.pants.reporting.html_reporter import HtmlReporter
from twitter.pants.reporting.quiet_reporter import QuietReporter
from twitter.pants.reporting.report import ReportingError, Report

StringIO = Compatibility.StringIO


def initial_reporting(config, run_tracker):
  """Sets up the initial reporting configuration.

  Will be changed after we parse cmd-line flags.
  """
  reports_dir = config.get('reporting', 'reports_dir')
  link_to_latest = os.path.join(reports_dir, 'latest')
  if os.path.exists(link_to_latest):
    os.unlink(link_to_latest)

  run_id = run_tracker.run_info.get_info('id')
  if run_id is None:
    raise ReportingError('No run_id set')
  run_dir = os.path.join(reports_dir, run_id)
  safe_rmtree(run_dir)

  html_dir = os.path.join(run_dir, 'html')
  safe_mkdir(html_dir)
  os.symlink(run_dir, link_to_latest)

  report = Report()

  # Capture initial console reporting into a buffer. We'll do something with it once
  # we know what the cmd-line flag settings are.
  outfile = StringIO()
  capturing_reporter_settings = PlainTextReporter.Settings(outfile=outfile, log_level=Report.INFO,
                                                           color=False, indent=True, timing=False,
                                                           cache_stats=False)
  capturing_reporter = PlainTextReporter(run_tracker, capturing_reporter_settings)
  report.add_reporter('capturing', capturing_reporter)

  # Set up HTML reporting. We always want that.
  template_dir = config.get('reporting', 'reports_template_dir')
  html_reporter_settings = HtmlReporter.Settings(log_level=Report.INFO,
                                                 html_dir=html_dir, template_dir=template_dir)
  html_reporter = HtmlReporter(run_tracker, html_reporter_settings)
  report.add_reporter('html', html_reporter)

  # Add some useful RunInfo.
  run_tracker.run_info.add_info('default_report', html_reporter.report_path())
  port = config.getint('reporting', 'reporting_port', -1)
  run_tracker.run_info.add_info('report_url', 'http://localhost:%d/run/%s' % (port, run_id))

  return report

def update_reporting(options, run_tracker):
  """Updates reporting config once we've parsed cmd-line flags."""

  # Get any output silently buffered in the old console reporter, and remove it.
  old_outfile = run_tracker.report.remove_reporter('capturing').settings.outfile
  old_outfile.flush()
  buffered_output = old_outfile.getvalue()
  old_outfile.close()

  log_level = Report.log_level_from_string(options.log_level or 'info')
  color = not options.no_color
  timing = options.time
  cache_stats = options.time  # TODO: Separate flag for this?

  if options.quiet:
    console_reporter = QuietReporter(run_tracker,
                                     QuietReporter.Settings(log_level=log_level, color=color))
  else:
    # Set up the new console reporter.
    settings = PlainTextReporter.Settings(log_level=log_level, outfile=sys.stdout, color=color,
                                          indent=True, timing=timing, cache_stats=cache_stats)
    console_reporter = PlainTextReporter(run_tracker, settings)
    console_reporter.emit(buffered_output)
    console_reporter.flush()
  run_tracker.report.add_reporter('console', console_reporter)

  if options.logdir:
    # Also write plaintext logs to a file. This is completely separate from the html reports.
    safe_mkdir(options.logdir)
    run_id = run_tracker.run_info.get_info('id')
    outfile = open(os.path.join(options.logdir, '%s.log' % run_id), 'w')
    settings = PlainTextReporter.Settings(log_level=log_level, outfile=outfile, color=False,
                                          indent=True, timing=True, cache_stats=True)
    logfile_reporter = PlainTextReporter(run_tracker, settings)
    logfile_reporter.emit(buffered_output)
    logfile_reporter.flush()
    run_tracker.report.add_reporter('logfile', logfile_reporter)
