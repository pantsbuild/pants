# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys
from io import BytesIO

from pants.base.workunit import WorkUnitLabel
from pants.reporting.html_reporter import HtmlReporter
from pants.reporting.invalidation_report import InvalidationReport
from pants.reporting.plaintext_reporter import LabelFormat, PlainTextReporter, ToolOutputFormat
from pants.reporting.quiet_reporter import QuietReporter
from pants.reporting.report import Report
from pants.reporting.reporter import ReporterDestination
from pants.reporting.reporting_server import ReportingServerManager
from pants.reporting.zipkin_reporter import ZipkinReporter
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import relative_symlink, safe_mkdir


class Reporting(Subsystem):
    options_scope = "reporting"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--invalidation-report",
            type=bool,
            help="Write a formatted report on the invalid objects to the specified path.",
        )
        register(
            "--reports-dir",
            advanced=True,
            metavar="<dir>",
            default=os.path.join(register.bootstrap.pants_workdir, "reports"),
            help="Write reports to this dir.",
        )
        register(
            "--template-dir",
            advanced=True,
            metavar="<dir>",
            default=None,
            help="Find templates for rendering in this dir.",
        )
        register(
            "--console-label-format",
            advanced=True,
            type=dict,
            default=PlainTextReporter.LABEL_FORMATTING,
            help="Controls the printing of workunit labels to the console.  Workunit types are "
            "{workunits}.  Possible formatting values are {formats}".format(
                workunits=list(WorkUnitLabel.keys()), formats=list(LabelFormat.keys())
            ),
        )
        register(
            "--console-tool-output-format",
            advanced=True,
            type=dict,
            default=PlainTextReporter.TOOL_OUTPUT_FORMATTING,
            help="Controls the printing of workunit tool output to the console. Workunit types are "
            "{workunits}.  Possible formatting values are {formats}".format(
                workunits=list(WorkUnitLabel.keys()), formats=list(ToolOutputFormat.keys())
            ),
        )
        register(
            "--zipkin-endpoint",
            advanced=True,
            default=None,
            help="The full HTTP URL of a zipkin server to which traces should be posted. "
            "No traces will be made if this is not set.",
        )
        register(
            "--zipkin-trace-id",
            advanced=True,
            default=None,
            help="The overall 64 or 128-bit ID of the trace (the format is 16-character or "
            "32-character hex string). Set if the Pants trace should be a part of a larger "
            "trace for systems that invoke Pants. If flags zipkin-trace-id and "
            "zipkin-parent-id are not set, a trace_id value is randomly generated "
            "for a Zipkin trace.",
        )
        register(
            "--zipkin-parent-id",
            advanced=True,
            default=None,
            help="The 64-bit ID for a parent span that invokes Pants (the format is 16-character "
            "hex string). Flags zipkin-trace-id and zipkin-parent-id must both either be set "
            "or not set when running a Pants command.",
        )
        register(
            "--zipkin-sample-rate",
            advanced=True,
            default=100.0,
            help="Rate at which to sample Zipkin traces. Value 0.0 - 100.0.",
        )
        register(
            "--zipkin-trace-v2",
            advanced=True,
            type=bool,
            default=False,
            help="If enabled, the zipkin spans are tracked for v2 engine execution progress.",
        )
        register(
            "--zipkin-service-name-prefix",
            advanced=True,
            default="pants",
            help="The prefix for service name for Zipkin spans.",
        )
        register(
            "--zipkin-max-span-batch-size",
            advanced=True,
            type=int,
            default=100,
            help="Spans in a Zipkin trace are sent to the Zipkin server in batches."
            "zipkin-max-span-batch-size sets the max size of one batch.",
        )

    def initialize(self, run_tracker, all_options, start_time=None):
        """Initialize with the given RunTracker.

        TODO: See `RunTracker.start`.
        """

        run_id, run_uuid = run_tracker.initialize(all_options)
        run_dir = os.path.join(self.get_options().reports_dir, run_id)

        html_dir = os.path.join(run_dir, "html")
        safe_mkdir(html_dir)
        relative_symlink(run_dir, os.path.join(self.get_options().reports_dir, "latest"))

        report = Report()

        # Capture initial console reporting into a buffer. We'll do something with it once
        # we know what the cmd-line flag settings are.
        outfile = BytesIO()
        errfile = BytesIO()
        capturing_reporter_settings = PlainTextReporter.Settings(
            outfile=outfile,
            errfile=errfile,
            log_level=Report.INFO,
            color=False,
            indent=True,
            timing=False,
            cache_stats=False,
            label_format=self.get_options().console_label_format,
            tool_output_format=self.get_options().console_tool_output_format,
        )
        capturing_reporter = PlainTextReporter(run_tracker, capturing_reporter_settings)
        report.add_reporter("capturing", capturing_reporter)

        # Set up HTML reporting. We always want that.
        html_reporter_settings = HtmlReporter.Settings(
            log_level=Report.INFO, html_dir=html_dir, template_dir=self.get_options().template_dir
        )
        html_reporter = HtmlReporter(run_tracker, html_reporter_settings)
        report.add_reporter("html", html_reporter)

        # Set up Zipkin reporting.
        zipkin_endpoint = self.get_options().zipkin_endpoint
        trace_id = self.get_options().zipkin_trace_id
        parent_id = self.get_options().zipkin_parent_id
        sample_rate = self.get_options().zipkin_sample_rate
        service_name_prefix = self.get_options().zipkin_service_name_prefix
        if "{}" not in service_name_prefix:
            service_name_prefix = service_name_prefix + "/{}"
        max_span_batch_size = int(self.get_options().zipkin_max_span_batch_size)

        if zipkin_endpoint is None and trace_id is not None and parent_id is not None:
            raise ValueError(
                "The zipkin-endpoint flag must be set if zipkin-trace-id and zipkin-parent-id flags are given."
            )
        if (trace_id is None) != (parent_id is None):
            raise ValueError(
                "Flags zipkin-trace-id and zipkin-parent-id must both either be set or not set."
            )

        # If trace_id isn't set by a flag, use UUID from run_id
        if trace_id is None:
            trace_id = run_uuid

        if trace_id and (
            len(trace_id) != 16 and len(trace_id) != 32 or not is_hex_string(trace_id)
        ):
            raise ValueError(
                "Value of the flag zipkin-trace-id must be a 16-character or 32-character hex string. "
                + "Got {}.".format(trace_id)
            )
        if parent_id and (len(parent_id) != 16 or not is_hex_string(parent_id)):
            raise ValueError(
                "Value of the flag zipkin-parent-id must be a 16-character hex string. "
                + "Got {}.".format(parent_id)
            )

        if zipkin_endpoint is not None:
            zipkin_reporter_settings = ZipkinReporter.Settings(log_level=Report.INFO)
            zipkin_reporter = ZipkinReporter(
                run_tracker,
                zipkin_reporter_settings,
                zipkin_endpoint,
                trace_id,
                parent_id,
                sample_rate,
                service_name_prefix,
                max_span_batch_size,
            )
            report.add_reporter("zipkin", zipkin_reporter)

        # Add some useful RunInfo.
        run_tracker.run_info.add_info("default_report", html_reporter.report_path())
        port = ReportingServerManager().socket
        if port:
            run_tracker.run_info.add_info(
                "report_url", "http://localhost:{}/run/{}".format(port, run_id)
            )

        # And start tracking the run.
        run_tracker.start(report, start_time)

    def _get_invalidation_report(self):
        return InvalidationReport() if self.get_options().invalidation_report else None

    @staticmethod
    def _consume_stringio(f):
        f.flush()
        buffered_output = f.getvalue()
        f.close()
        return buffered_output

    def update_reporting(self, global_options, is_quiet, run_tracker):
        """Updates reporting config once we've parsed cmd-line flags."""

        # Get any output silently buffered in the old console reporter, and remove it.
        removed_reporter = run_tracker.report.remove_reporter("capturing")
        buffered_out = self._consume_stringio(removed_reporter.settings.outfile)
        buffered_err = self._consume_stringio(removed_reporter.settings.errfile)

        log_level = Report.report_level_from_log_level(global_options.level)
        # Ideally, we'd use terminfo or somesuch to discover whether a
        # terminal truly supports color, but most that don't set TERM=dumb.
        color = global_options.colors and (os.getenv("TERM") != "dumb")
        timing = global_options.time
        cache_stats = global_options.time  # TODO: Separate flag for this?

        if is_quiet:
            console_reporter = QuietReporter(
                run_tracker,
                QuietReporter.Settings(
                    log_level=log_level, color=color, timing=timing, cache_stats=cache_stats
                ),
            )
        else:
            # Set up the new console reporter.
            stdout = sys.stdout.buffer
            stderr = sys.stderr.buffer
            settings = PlainTextReporter.Settings(
                log_level=log_level,
                outfile=stdout,
                errfile=stderr,
                color=color,
                indent=True,
                timing=timing,
                cache_stats=cache_stats,
                label_format=self.get_options().console_label_format,
                tool_output_format=self.get_options().console_tool_output_format,
            )
            console_reporter = PlainTextReporter(run_tracker, settings)
            console_reporter.emit(buffered_out, dest=ReporterDestination.OUT)
            console_reporter.emit(buffered_err, dest=ReporterDestination.ERR)
            console_reporter.flush()
        run_tracker.report.add_reporter("console", console_reporter)

        if global_options.logdir:
            # Also write plaintext logs to a file. This is completely separate from the html reports.
            safe_mkdir(global_options.logdir)
            run_id = run_tracker.run_info.get_info("id")
            outfile = open(os.path.join(global_options.logdir, "{}.log".format(run_id)), "wb")
            errfile = open(os.path.join(global_options.logdir, "{}.err.log".format(run_id)), "wb")
            settings = PlainTextReporter.Settings(
                log_level=log_level,
                outfile=outfile,
                errfile=errfile,
                color=False,
                indent=True,
                timing=True,
                cache_stats=True,
                label_format=self.get_options().console_label_format,
                tool_output_format=self.get_options().console_tool_output_format,
            )
            logfile_reporter = PlainTextReporter(run_tracker, settings)
            logfile_reporter.emit(buffered_out, dest=ReporterDestination.OUT)
            logfile_reporter.emit(buffered_err, dest=ReporterDestination.ERR)
            logfile_reporter.flush()
            run_tracker.report.add_reporter("logfile", logfile_reporter)

        invalidation_report = self._get_invalidation_report()
        if invalidation_report:
            run_id = run_tracker.run_info.get_info("id")
            outfile = os.path.join(
                self.get_options().reports_dir, run_id, "invalidation-report.csv"
            )
            invalidation_report.set_filename(outfile)

        return invalidation_report


def is_hex_string(id_value):
    return all(is_hex_ch(ch) for ch in id_value)


def is_hex_ch(ch):
    num = ord(ch)
    return ord("0") <= num <= ord("9") or ord("a") <= num <= ord("f") or ord("A") <= num <= ord("F")
