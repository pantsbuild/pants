import os

from twitter.common.dirutil import safe_mkdir, safe_rmtree

from twitter.pants.reporting.console_reporter import ConsoleReporter
from twitter.pants.reporting.html_reporter import HtmlReporter
from twitter.pants.reporting.report import ReportingError, Report


def default_report(config, run_tracker):
  """Sets up the default reporting configuration."""
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

  console_reporter_settings = ConsoleReporter.Settings(log_level=Report.INFO, color=False,
                                                       indent=True, timing=False, cache_stats=False)
  console_reporter = ConsoleReporter(run_tracker, console_reporter_settings)

  template_dir = config.get('reporting', 'reports_template_dir')
  html_reporter_settings = HtmlReporter.Settings(log_level=Report.INFO,
                                                 html_dir=html_dir, template_dir=template_dir)
  html_reporter = HtmlReporter(run_tracker, html_reporter_settings)

  report.add_reporter('console', console_reporter)
  report.add_reporter('html', html_reporter)

  run_tracker.run_info.add_info('default_report', html_reporter.report_path())

  return report
