# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple

import six
from colors import cyan, green, red, yellow

from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.reporting.report import Report
from pants.reporting.reporter import Reporter
from pants.util.memo import memoized_method


class ToolOutputFormat(object):
  """Configuration item for displaying Tool Output to the console."""

  SUPPRESS =   'SUPPRESS'    # Do not display output from the workunit unless its outcome != SUCCESS
  INDENT =     'INDENT'      # Indent the output to line up with the indentation of the other log output
  UNINDENTED = 'UNINDENTED'  # Display the output raw, with no leading indentation

  @classmethod
  @memoized_method
  def keys(cls):
    return [key for key in dir(cls) if not key.startswith('_') and key.isupper()]


class LabelFormat(object):
  """Configuration item for displaying a workunit label to the console."""

  SUPPRESS = 'SUPPRESS'              # Don't show the label at all
  DOT = 'DOT'                        # Just output a single '.' with no newline
  FULL = 'FULL'                      # Show the timestamp and label
  CHILD_SUPPRESS = 'CHILD_SUPPRESS'  # Suppress labels for all children of this node
  CHILD_DOT = 'CHILD_DOT'            # Display a dot for all children of this node

  @classmethod
  @memoized_method
  def keys(cls):
    return [key for key in dir(cls) if not key.startswith('_') and key.isupper()]


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
                        Reporter.Settings._fields + ('outfile', 'color', 'indent', 'timing',
                                                     'cache_stats', 'label_format',
                                                     'tool_output_format'))

  _COLOR_BY_LEVEL = {
    Report.FATAL: red,
    Report.ERROR: red,
    Report.WARN: yellow,
    Report.INFO: green,
    Report.DEBUG: cyan
  }

  # Format the std output from these workunit types as specified.  If no format is specified, the
  # default is ToolOutputFormat.SUPPRESS
  TOOL_OUTPUT_FORMATTING = {
    WorkUnitLabel.MULTITOOL: ToolOutputFormat.SUPPRESS,
    WorkUnitLabel.BOOTSTRAP: ToolOutputFormat.SUPPRESS,
    WorkUnitLabel.COMPILER : ToolOutputFormat.INDENT,
    WorkUnitLabel.TEST : ToolOutputFormat.INDENT,
    WorkUnitLabel.REPL : ToolOutputFormat.UNINDENTED,
    WorkUnitLabel.RUN : ToolOutputFormat.UNINDENTED
  }

  # Format the labels from these workunit types as specified.  If no format is specified, the
  # default is LabelFormat.FULL
  LABEL_FORMATTING = {
    WorkUnitLabel.MULTITOOL: LabelFormat.CHILD_DOT,
    WorkUnitLabel.BOOTSTRAP: LabelFormat.CHILD_SUPPRESS,
  }

  def __init__(self, run_tracker, settings):
    Reporter.__init__(self, run_tracker, settings)
    for key, value in settings.label_format.items():
      if key not in WorkUnitLabel.keys():
        self.emit('*** Got invalid key {} for --reporting-console-label-format. Expected one of {}\n'
                  .format(key, WorkUnitLabel.keys()))
      if value not in LabelFormat.keys():
        self.emit('*** Got invalid value {} for --reporting-console-label-format. Expected one of {}\n'
                  .format(value, LabelFormat.keys()))
    for key, value in settings.tool_output_format.items():
      if key not in WorkUnitLabel.keys():
        self.emit('*** Got invalid key {} for --reporting-console-tool-output-format. Expected one of {}\n'
                  .format(key, WorkUnitLabel.keys()))
      if value not in ToolOutputFormat.keys():
        self.emit('*** Got invalid value {} for --reporting-console-tool-output-format. Expected one of {}\n'
                  .format(value, ToolOutputFormat.keys()))

    # Mix in the new settings with the defaults.
    self.LABEL_FORMATTING.update(settings.label_format.items())
    self.TOOL_OUTPUT_FORMATTING.update(settings.tool_output_format.items())

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

    label_format = self._get_label_format(workunit)

    if label_format == LabelFormat.FULL:
      self._emit_indented_workunit_label(workunit)
      # Start output on a new line.
      tool_output_format = self._get_tool_output_format(workunit)
      if tool_output_format == ToolOutputFormat.INDENT:
        self.emit(self._prefix(workunit, b'\n'))
      elif tool_output_format == ToolOutputFormat.UNINDENTED:
        self.emit(b'\n')
    elif label_format == LabelFormat.DOT:
      self.emit(b'.')

    self.flush()

  def end_workunit(self, workunit):
    """Implementation of Reporter callback."""
    if not self.is_under_main_root(workunit):
      return

    if workunit.outcome() != WorkUnit.SUCCESS and not self._show_output(workunit):
      # Emit the suppressed workunit output, if any, to aid in debugging the problem.
      if self._get_label_format(workunit) != LabelFormat.FULL:
        self._emit_indented_workunit_label(workunit)
      for name, outbuf in workunit.outputs().items():
        self.emit(self._prefix(workunit, b'\n==== {} ====\n'.format(name)))
        self.emit(self._prefix(workunit, outbuf.read_from(0)))
        self.flush()

  def do_handle_log(self, workunit, level, *msg_elements):
    """Implementation of Reporter callback."""
    if not self.is_under_main_root(workunit):
      return

    # If the element is a (msg, detail) pair, we ignore the detail. There's no
    # useful way to display it on the console.
    elements = [e if isinstance(e, six.string_types) else e[0] for e in msg_elements]
    msg = b'\n' + b''.join(elements)
    if self.use_color_for_workunit(workunit, self.settings.color):
      msg = self._COLOR_BY_LEVEL.get(level, lambda x: x)(msg)

    self.emit(self._prefix(workunit, msg))
    self.flush()

  def handle_output(self, workunit, label, s):
    """Implementation of Reporter callback."""
    if not self.is_under_main_root(workunit):
      return
    tool_output_format = self._get_tool_output_format(workunit)
    if tool_output_format == ToolOutputFormat.INDENT:
      self.emit(self._prefix(workunit, s))
    elif tool_output_format == ToolOutputFormat.UNINDENTED:
      self.emit(s)
    self.flush()

  def emit(self, s):
    self.settings.outfile.write(s)

  def flush(self):
    self.settings.outfile.flush()

  def _get_label_format(self, workunit):
    for label, label_format in self.LABEL_FORMATTING.items():
      if workunit.has_label(label):
        return label_format

    # Recursively look for a setting to suppress child label formatting.
    if workunit.parent:
      label_format = self._get_label_format(workunit.parent)
      if label_format == LabelFormat.CHILD_DOT:
        return LabelFormat.DOT
      if label_format == LabelFormat.CHILD_SUPPRESS:
        return LabelFormat.SUPPRESS

    return LabelFormat.FULL

  def _get_tool_output_format(self, workunit):
    for label, tool_output_format in self.TOOL_OUTPUT_FORMATTING.items():
      if workunit.has_label(label):
        return tool_output_format

    return ToolOutputFormat.SUPPRESS

  def _emit_indented_workunit_label(self, workunit):
    self.emit(b'\n{} {} {}[{}]'.format(
      workunit.start_time_string(),
      workunit.start_delta_string(),
      self._indent(workunit),
      workunit.name if self.settings.indent else workunit.path()))

  # Emit output from some tools and not others.
  # This is an arbitrary choice, but one that turns out to be useful to users in practice.
  def _show_output(self, workunit):
    tool_output_format = self._get_tool_output_format(workunit)
    return not tool_output_format == ToolOutputFormat.SUPPRESS

  def _format_aggregated_timings(self, aggregated_timings):
    return b'\n'.join([b'{timing:.3f} {label}'.format(**x) for x in aggregated_timings.get_all()])

  def _format_artifact_cache_stats(self, artifact_cache_stats):
    stats = artifact_cache_stats.get_all()
    return b'No artifact cache reads.' if not stats else \
    b'\n'.join([b'{cache_name} - Hits: {num_hits} Misses: {num_misses}'.format(**x)
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
