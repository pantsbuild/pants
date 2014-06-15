# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import namedtuple

from pants.base.workunit import WorkUnit
from pants.reporting.report import Report
from pants.reporting.reporter import Reporter

from colors import cyan, green, red, yellow


class PlainTextReporter(Reporter):
  """Plain-text reporting to stdout.

  We only report progress for things under the default work root. It gets too
  confusing to try and show progress for background work too.
  """

  # Console reporting settings.
  #   outfile: Write to this file-like object.
  #   color: use ANSI colors in output.
  #   indent: Whether to indent the reporting to reflect the nesting of workunits.
  #   timing: Show timing report at the end of the run.
  #   cache_stats: Show artifact cache report at the end of the run.
  Settings = namedtuple('Settings',
                        Reporter.Settings._fields + ('outfile', 'color', 'indent', 'timing', 'cache_stats'))

  _COLOR_BY_LEVEL = {
    Report.FATAL: red,
    Report.ERROR: red,
    Report.WARN: yellow,
    Report.INFO: green,
    Report.DEBUG: cyan
  }

  def __init__(self, run_tracker, settings):
    Reporter.__init__(self, run_tracker, settings)

  def open(self):
    """Implementation of Reporter callback."""
    pass

  def close(self):
    """Implementation of Reporter callback."""
    if self.settings.timing:
      self.emit(b'\n')
      self.emit(b'\nCumulative Timings')
      self.emit(b'\n==================')
      self.emit(b'\n')
      self.emit(self._format_aggregated_timings(self.run_tracker.cumulative_timings))
      self.emit(b'\n')
      self.emit(b'\nSelf Timings')
      self.emit(b'\n============')
      self.emit(b'\n')
      self.emit(self._format_aggregated_timings(self.run_tracker.self_timings))
    if self.settings.cache_stats:
      self.emit(b'\n')
      self.emit(b'\nArtifact Cache Stats')
      self.emit(b'\n====================')
      self.emit(b'\n')
      self.emit(self._format_artifact_cache_stats(self.run_tracker.artifact_cache_stats))
    self.emit(b'\n')

  def start_workunit(self, workunit):
    """Implementation of Reporter callback."""
    if not self.is_under_main_root(workunit):
      return

    if workunit.parent and workunit.parent.has_label(WorkUnit.MULTITOOL):
      # For brevity, we represent each consecutive invocation of a multitool with a dot.
      self.emit(b'.')
    elif not workunit.parent or \
        all([not x.has_label(WorkUnit.MULTITOOL) and not x.has_label(WorkUnit.BOOTSTRAP)
             for x in workunit.parent.ancestors()]):
      # Bootstrapping can be chatty, so don't show anything for its sub-workunits.
      self.emit(b'\n%s %s %s[%s]' %
                       (workunit.start_time_string(),
                        workunit.start_delta_string(),
                        self._indent(workunit),
                        workunit.name if self.settings.indent else workunit.path()))
      # Start output on a new line.
      if self._show_output_indented(workunit):
        self.emit(self._prefix(workunit, b'\n'))
      elif self._show_output_unindented(workunit):
        self.emit(b'\n')
    self.flush()

  def end_workunit(self, workunit):
    """Implementation of Reporter callback."""
    if not self.is_under_main_root(workunit):
      return

    if workunit.outcome() != WorkUnit.SUCCESS and not self._show_output(workunit):
      # Emit the suppressed workunit output, if any, to aid in debugging the problem.
      for name, outbuf in workunit.outputs().items():
        self.emit(self._prefix(workunit, b'\n==== %s ====\n' % name))
        self.emit(self._prefix(workunit, outbuf.read_from(0)))
        self.flush()

  def do_handle_log(self, workunit, level, *msg_elements):
    """Implementation of Reporter callback."""
    if not self.is_under_main_root(workunit):
      return

    # If the element is a (msg, detail) pair, we ignore the detail. There's no
    # useful way to display it on the console.
    elements = [e if isinstance(e, basestring) else e[0] for e in msg_elements]
    msg = b'\n' + b''.join(elements)
    if self.settings.color:
      msg = self._COLOR_BY_LEVEL.get(level, lambda x: x)(msg)
    self.emit(self._prefix(workunit, msg))
    self.flush()

  def handle_output(self, workunit, label, s):
    """Implementation of Reporter callback."""
    if not self.is_under_main_root(workunit):
      return

    if self._show_output_indented(workunit):
      self.emit(self._prefix(workunit, s))
    elif self._show_output_unindented(workunit):
      self.emit(s)
    self.flush()

  def emit(self, s):
    self.settings.outfile.write(s)

  def flush(self):
    self.settings.outfile.flush()

  # Emit output from some tools and not others.
  # This is an arbitrary choice, but one that turns out to be useful to users in practice.

  def _show_output(self, workunit):
    return self._show_output_indented(workunit) or self._show_output_unindented(workunit)

  def _show_output_indented(self, workunit):
    return workunit.has_label(WorkUnit.COMPILER) or workunit.has_label(WorkUnit.TEST)

  def _show_output_unindented(self, workunit):
    # Indenting looks weird in these cases.
    return workunit.has_label(WorkUnit.REPL) or workunit.has_label(WorkUnit.RUN)


  def _format_aggregated_timings(self, aggregated_timings):
    return b'\n'.join([b'%(timing).3f %(label)s' % x for x in aggregated_timings.get_all()])

  def _format_artifact_cache_stats(self, artifact_cache_stats):
    stats = artifact_cache_stats.get_all()
    return b'No artifact cache reads.' if not stats else \
    b'\n'.join([b'%(cache_name)s - Hits: %(num_hits)d Misses: %(num_misses)d' % x
                for x in stats])

  def _indent(self, workunit):
    return b'  ' * (len(workunit.ancestors()) - 1)

  _time_string_filler = b' ' * len('HH:MM:SS mm:ss ')

  def _prefix(self, workunit, s):
    if self.settings.indent:
      def replace(x, c):
        return x.replace(c, c + PlainTextReporter._time_string_filler + self._indent(workunit))
      return replace(replace(s, b'\r'), b'\n')
    else:
      return PlainTextReporter._time_string_filler + s
