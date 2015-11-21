# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import cgi
import os
import re
import time
import uuid
from collections import defaultdict, namedtuple
from textwrap import dedent

from six import string_types
from six.moves import range

from pants.base.build_environment import get_buildroot
from pants.base.mustache import MustacheRenderer
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.reporting.linkify import linkify
from pants.reporting.report import Report
from pants.reporting.reporter import Reporter
from pants.reporting.reporting_utils import items_to_report_element
from pants.util.dirutil import safe_mkdir


class HtmlReporter(Reporter):
  """HTML reporting to files.

  The files are intended to be served by the ReportingServer,
  not accessed directly from the filesystem.

  Pages are rendered using mustache templates, but individual fragments (appended to the report
  of a currently running Pants run) are rendered using python string.format(), because it's
  significantly faster, and profiles showed that the difference was non-trivial in short
  pants runs.

  TODO: The entire HTML reporting system, and the pants server that backs it, should be
  rewritten to use some modern webapp framework, instead of this combination of server-side
  ad-hoc templates and client-side spaghetti code.
  """

  # HTML reporting settings.
  #   html_dir: Where the report files go.
  #   template_dir: Where to find mustache templates.
  Settings = namedtuple('Settings', Reporter.Settings._fields + ('html_dir', 'template_dir'))

  def __init__(self, run_tracker, settings):
    super(HtmlReporter, self).__init__(run_tracker, settings)
     # The main report, and associated tool outputs, go under this dir.
    self._html_dir = settings.html_dir

    # We render HTML from mustache templates.
    self._renderer = MustacheRenderer(settings.template_dir, __name__)

    # We serve files relative to the build root.
    self._buildroot = get_buildroot()
    self._html_path_base = os.path.relpath(self._html_dir, self._buildroot)

    # We write the main report body to this file object.
    self._report_file = None

    # We redirect stdout, stderr etc. of tool invocations to these files.
    self._output_files = defaultdict(dict)  # workunit_id -> {path -> fileobj}.
    self._linkify_memo = {}

    # Map from filename to timestamp (ms since the epoch) of when we last overwrote that file.
    # Useful for preventing too-frequent overwrites of, e.g., timing stats,
    # which can noticeably slow down short pants runs with many workunits.
    self._last_overwrite_time = {}

  def report_path(self):
    """The path to the main report file."""
    return os.path.join(self._html_dir, 'build.html')

  def open(self):
    """Implementation of Reporter callback."""
    safe_mkdir(os.path.dirname(self._html_dir))
    self._report_file = open(self.report_path(), 'w')

  def close(self):
    """Implementation of Reporter callback."""
    self._report_file.close()
    # Make sure everything's closed.
    for files in self._output_files.values():
      for f in files.values():
        f.close()

  # Creates a collapsible div in which to nest the reporting for a workunit.
  # To add content to this div, append it to ${'#WORKUNITID-content'}.
  # Note that definitive workunit timing is done in pants, but the client-side timer in the js
  # below allows us to show a running timer in the browser while the workunit is executing.
  _start_workunit_fmt_string = dedent("""
    <div id="__{id}__content">
      <div id="{id}">
        <div class="toggle-header" id="{id}-header">
          <div class="toggle-header-icon" onclick="pants.collapsible.toggle('{id}')">
            <i id="{id}-icon" class="visibility-icon icon-large icon-caret-{icon_caret} hidden"></i>
          </div>
          <div class="toggle-header-text">
            <div class="timeprefix">
              <span class="timestamp">{workunit.start_time_string}</span>
              <span class="timedelta">{workunit.start_delta_string}</span>
            </div>
            [<span id="{id}-header-text">{workunit.name}</span>]
            <span class="timer" id="{id}-timer"></span>
            <i class="icon-{icon}"></i>
            <span class="aborted nodisplay" id="{id}-aborted">ctrl-c</span>
            <span class="unaccounted-time nodisplay" id="{id}-unaccounted-time"></span>
          </div>
          <div id="{id}-spinner"><i class="icon-spinner icon-spin icon-large"></i></div>
        </div>
        <div class="toggle-content {display_class}" id="{id}-content"></div>
      </div>
    </div>
    <script>
      $(function() {{
        if ('{parent_id}' !== '') {{
          pants.append('#__{id}__content', '#{parent_id}-content');
          $('#{parent_id}-icon').removeClass('hidden');
          pants.timerManager.startTimer('{id}', '#{id}-timer', 1000 * {workunit.start_time});
        }}
      }});
    </script>
  """)

  _start_tool_invocation_fmt_string = dedent("""
    <div id="__{id}__tool_invocation">
    {tool_invocation_details}
    </div>
    <script>
      $(function() {{
        pants.collapsible.hasContent('{id}');
        pants.collapsible.hasContent('{id}-cmd');
        pants.append('#__{id}__tool_invocation', '#{id}-content');
        pants.appendString('{cmd}', '#{id}-cmd-content');
        var startTailing = function() {{
          pants.poller.startTailing('{id}_stdout', '{html_path_base}/{id}.stdout',
          '#{id}-stdout-content', function() {{ pants.collapsible.hasContent('{id}-stdout'); }});
          pants.poller.startTailing('{id}_stderr', '{html_path_base}/{id}.stderr',
          '#{id}-stderr-content', function() {{ pants.collapsible.hasContent('{id}-stderr'); }});
        }}
        if ($('#{id}-content').is(':visible')) {{
          startTailing();
        }} else {{
          $('#{id}-header').one('click', startTailing);
        }}
      }});
    </script>
  """)

  def start_workunit(self, workunit):
    """Implementation of Reporter callback."""
    # We use these properties of the workunit to decide how to render information about it.
    is_bootstrap = workunit.has_label(WorkUnitLabel.BOOTSTRAP)
    is_tool = workunit.has_label(WorkUnitLabel.TOOL)
    is_multitool = workunit.has_label(WorkUnitLabel.MULTITOOL)
    is_test = workunit.has_label(WorkUnitLabel.TEST)

    initially_open = is_test or not (is_bootstrap or is_tool or is_multitool)

    # Render the workunit's div.
    s = self._start_workunit_fmt_string.format(
      indent=len(workunit.ancestors()) * 10,
      id=workunit.id,
      parent_id=workunit.parent.id if workunit.parent else '',
      workunit=workunit,
      icon_caret='down' if initially_open else 'right',
      display_class='' if initially_open else 'nodisplay',
      icon='cog' if is_tool else 'cogs' if is_multitool else 'none'
    )
    self._emit(s)

    if is_tool:
      tool_invocation_details = '\n'.join([
        self._render_tool_detail(workunit=workunit, title='cmd', class_prefix='cmd'),
        # Have test framework stdout open by default, but not that of other tools.
        # This is an arbitrary choice, but one that turns out to be useful to users in practice.
        self._render_tool_detail(workunit=workunit, title='stdout', initially_open=is_test),
        self._render_tool_detail(workunit=workunit, title='stderr'),
      ])

      cmd = workunit.cmd or ''
      linkified_cmd = linkify(self._buildroot, cmd.replace('$', '\\\\$'), self._linkify_memo)

      s = self._start_tool_invocation_fmt_string.format(
        tool_invocation_details=tool_invocation_details,
        html_path_base=self._html_path_base,
        id=workunit.id,
        cmd=linkified_cmd
      )

      self._emit(s)

  # CSS classes from pants.css that we use to style the header text to reflect the outcome.
  _outcome_css_classes = ['aborted', 'failure', 'warning', 'success', 'unknown']

  _end_tool_invocation_fmt_string = dedent("""
    <script>
      $('#{id}-header-text').addClass('{status}'); $('#{id}-spinner').hide();
      pants.poller.stopTailing('{id}_stdout');
      pants.poller.stopTailing('{id}_stderr');
    </script>
  """)

  _end_workunit_fmt_string = dedent("""
    <script>
      $('#{id}-header-text').addClass('{status}');
      $('#{id}-spinner').hide();
      $('#{id}-timer').html('{timing}s');
      if ({aborted}) {{
        $('#{id}-aborted').show();
      }} else if ('{unaccounted_time}' !== '') {{
        $('#{id}-unaccounted-time').html('(Unaccounted: {unaccounted_time}s)').show();
      }}
      $(function(){{
        pants.timerManager.stopTimer('{id}');
      }});
    </script>
  """)

  def end_workunit(self, workunit):
    """Implementation of Reporter callback."""
    duration = workunit.duration()
    timing = '{:.3f}'.format(duration)
    unaccounted_time = ''
    # Background work may be idle a lot, no point in reporting that as unaccounted.
    if self.is_under_main_root(workunit):
      unaccounted_time_secs = workunit.unaccounted_time()
      if unaccounted_time_secs >= 1 and unaccounted_time_secs > 0.05 * duration:
        unaccounted_time = '{:.3f}'.format(unaccounted_time_secs)

    status = HtmlReporter._outcome_css_classes[workunit.outcome()]

    if workunit.has_label(WorkUnitLabel.TOOL):
      self._emit(self._end_tool_invocation_fmt_string.format(
        id=workunit.id,
        status=status
      ))

    self._emit(self._end_workunit_fmt_string.format(
      id=workunit.id,
      status=status,
      timing=timing,
      unaccounted_time=unaccounted_time,
      aborted='true' if workunit.outcome() == WorkUnit.ABORTED else 'false'
    ))

    # If we're a root workunit, force an overwrite, as we may be the last ever write in this run.
    force_overwrite = workunit.parent is None

    # Update the timings.
    def render_timings(timings):
      timings_dict = timings.get_all()
      for item in timings_dict:
        item['timing_string'] = '{:.3f}'.format(item['timing'])

      res = ['<table>']
      for item in timings_dict:
        res.append("""<tr><td class="timing-string">{timing:.3f}</td>
                          <td class="timing-label">{label}""".format(
          timing=item['timing'],
          label=item['label']
        ))
        if item['is_tool']:
          res.append("""<i class="icon-cog"></i>""")
        res.append("""</td></tr>""")
      res.append('<table>')

      return ''.join(res)

    self._overwrite('cumulative_timings',
                    lambda: render_timings(self.run_tracker.cumulative_timings),
                    force=force_overwrite)
    self._overwrite('self_timings',
                    lambda: render_timings(self.run_tracker.self_timings),
                    force=force_overwrite)

    # Update the artifact cache stats.
    def render_cache_stats(artifact_cache_stats):
      def fix_detail_id(e, _id):
        return e if isinstance(e, string_types) else e + (_id, )

      msg_elements = []
      for cache_name, stat in artifact_cache_stats.stats_per_cache.items():
        msg_elements.extend([
          cache_name + ' artifact cache: ',
          # Explicitly set the detail ids, so their displayed/hidden state survives a refresh.
          fix_detail_id(items_to_report_element(stat.hit_targets, 'hit'), 'cache-hit-details'),
          ', ',
          fix_detail_id(items_to_report_element(stat.miss_targets, 'miss'), 'cache-miss-details'),
          '.'
        ])
      if not msg_elements:
        msg_elements = ['No artifact cache use.']
      return self._render_message(*msg_elements)

    self._overwrite('artifact_cache_stats',
                    lambda: render_cache_stats(self.run_tracker.artifact_cache_stats),
                    force=force_overwrite)

    for f in self._output_files[workunit.id].values():
      f.close()

  def handle_output(self, workunit, label, s):
    """Implementation of Reporter callback."""
    if os.path.exists(self._html_dir):  # Make sure we're not immediately after a clean-all.
      path = os.path.join(self._html_dir, '{}.{}'.format(workunit.id, label))
      output_files = self._output_files[workunit.id]
      if path not in output_files:
        f = open(path, 'w')
        output_files[path] = f
      else:
        f = output_files[path]
      f.write(self._htmlify_text(s).encode('utf-8'))
      # We must flush in the same thread as the write.
      f.flush()

  _log_level_css_map = {
    Report.FATAL: 'fatal',
    Report.ERROR: 'error',
    Report.WARN: 'warn',
    Report.INFO: 'info',
    Report.DEBUG: 'debug'
  }

  _log_fmt_string = dedent("""
    <div id="__{content_id}"><span class="{css_class}">{message}</span></div>
    <script>
      $(function(){{
        pants.append('#__{content_id}', '#{workunit_id}-content');
      }});
    </script>
  """)

  def do_handle_log(self, workunit, level, *msg_elements):
    """Implementation of Reporter callback."""
    message = self._render_message(*msg_elements)
    s = self._log_fmt_string.format(content_id=uuid.uuid4(),
                                    workunit_id=workunit.id,
                                    css_class=HtmlReporter._log_level_css_map[level],
                                    message=message)

    # Emit that javascript to the main report body.
    self._emit(s)

  _detail_a_fmt_string = dedent("""
      <a href="#" onclick="$('.{detail_class}').not('#{detail_id}').hide();
                           $('#{detail_id}').toggle(); return false;">{text}</a>
  """)

  _detail_div_fmt_string = dedent("""
      <div id="{detail_id}" class="{detail_class} {detail_visibility_class}">{detail}</div>
  """)

  def _render_message(self, *msg_elements):
    # Identifies all details in this message, so that opening one can close all the others.
    detail_class = str(uuid.uuid4())

    html_fragments = ['<div>']

    detail_divs = []
    for element in msg_elements:
      # Each element can be a message or a (message, detail) pair, as received by handle_log().
      #
      # However, as an internal implementation detail, we also allow an element to be a tuple
      # (message, detail, detail_initially_visible[, detail_id])
      #
      # - If the detail exists, clicking on the text will toggle display of the detail and close
      #   all other details in this message.
      # - If detail_initially_visible is True, the detail will be displayed by default.
      #
      # We allow detail_id to be explicitly specified, so that the open/closed state can be
      # preserved through refreshes. For example, when looking at the artifact cache stats,
      # if "hits" are open and "misses" are closed, we want to remember that even after
      # the cache stats are updated and the message re-rendered.
      if isinstance(element, string_types):
        element = [element]

      # Map assumes None for missing values, so this will pick the default for those.
      (text, detail, detail_id, detail_initially_visible) = \
        map(lambda x, y: x or y, element, ('', None, None, False))

      htmlified_text = self._htmlify_text(text)

      if detail is None:
        html_fragments.append(htmlified_text)
      else:
        detail_id = detail_id or str(uuid.uuid4())
        detail_visibility_class = '' if detail_initially_visible else 'nodisplay'
        html_fragments.append(self._detail_a_fmt_string.format(
            text=htmlified_text, detail_id=detail_id, detail_class=detail_class))
        detail_divs.append(self._detail_div_fmt_string.format(
          detail_id=detail_id, detail=detail, detail_class=detail_class,
          detail_visibility_class=detail_visibility_class
        ))
    html_fragments.extend(detail_divs)
    html_fragments.append('</div>')

    return ''.join(html_fragments)

  _tool_detail_fmt_string = dedent("""
    <div class="{class_prefix}" id="{id}">
      <div class="{class_prefix}-header toggle-header" id="{id}-header">
        <div class="{class_prefix}-header-icon toggle-header-icon"
             onclick="pants.collapsible.toggle('{id}')">
          <i id="{id}-icon" class="visibility-icon icon-large icon-caret-{icon_caret} hidden"></i>
        </div>
        <div class="{class_prefix}-header-text toggle-header-text">
          [<span id="{id}-header-text">{title}</span>]
        </div>
      </div>
      <div class="{class_prefix}-content toggle-content {display_class}" id="{id}-content"></div>
    </div>
  """)

  def _render_tool_detail(self, workunit, title, class_prefix='greyed', initially_open=False):
    return self._tool_detail_fmt_string.format(
      class_prefix=class_prefix,
      id='{}-{}'.format(workunit.id, title),
      icon_caret='down' if initially_open else 'right',
      display_class='' if initially_open else 'nodisplay',
      title=title,
    )

  def _emit(self, s):
    """Append content to the main report file."""
    if os.path.exists(self._html_dir):  # Make sure we're not immediately after a clean-all.
      self._report_file.write(s)
      self._report_file.flush()  # We must flush in the same thread as the write.

  def _overwrite(self, filename, func, force=False):
    """Overwrite a file with the specified contents.

    Write times are tracked, too-frequent overwrites are skipped, for performance reasons.

    :param filename: The path under the html dir to write to.
    :param func: A no-arg function that returns the contents to write.
    :param force: Whether to force a write now, regardless of the last overwrite time.
    """
    now = int(time.time() * 1000)
    last_overwrite_time = self._last_overwrite_time.get(filename) or now
    # Overwrite only once per second.
    if (now - last_overwrite_time >= 1000) or force:
      if os.path.exists(self._html_dir):  # Make sure we're not immediately after a clean-all.
        with open(os.path.join(self._html_dir, filename), 'w') as f:
          f.write(func())
      self._last_overwrite_time[filename] = now

  def _htmlify_text(self, s):
    """Make text HTML-friendly."""
    colored = self._handle_ansi_color_codes(cgi.escape(s.decode('utf-8')))
    return linkify(self._buildroot, colored, self._linkify_memo).replace('\n', '</br>')

  _ANSI_COLOR_CODE_RE = re.compile(r'\033\[((?:\d|;)*)m')

  def _handle_ansi_color_codes(self, s):
    """Replace ansi escape sequences with spans of appropriately named css classes."""
    parts = HtmlReporter._ANSI_COLOR_CODE_RE.split(s)
    ret = []
    span_depth = 0
    # Note that len(parts) is always odd: text, code, text, code, ..., text.
    for i in range(0, len(parts), 2):
      ret.append(parts[i])
      if i + 1 < len(parts):
        for code in parts[i + 1].split(';'):
          if code == 0:  # Reset.
            while span_depth > 0:
              ret.append('</span>')
              span_depth -= 1
          else:
            ret.append('<span class="ansi-{}">'.format(code))
            span_depth += 1
    while span_depth > 0:
      ret.append('</span>')
      span_depth -= 1

    return ''.join(ret)
