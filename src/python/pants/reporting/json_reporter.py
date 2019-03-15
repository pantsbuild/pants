# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os
from builtins import list, open, str
from collections import defaultdict, namedtuple

from future.moves.itertools import zip_longest
from six import string_types

from pants.base.build_environment import get_buildroot
from pants.reporting.reporter import Reporter
from pants.util.dirutil import safe_mkdir


class JsonReporter(Reporter):
  """Json reporting to files."""

  _log_level_str = [
    'FATAL',
    'ERROR',
    'WARN',
    'INFO',
    'DEBUG',
  ]

  # JSON reporting settings.
  #   json_dir: Where the report files go.
  Settings = namedtuple('Settings', Reporter.Settings._fields + ('json_dir',))

  def __init__(self, run_tracker, settings):
    super(JsonReporter, self).__init__(run_tracker, settings)
    # The main report, and associated tool outputs, go under this dir.
    self._json_dir = settings.json_dir

    self._buildroot = get_buildroot()
    self._report_file = None

    # Results of the state of the build
    self._results = {}
    # Workunit stacks partitioned by thread
    self._stack_per_thread = defaultdict(list)

  def report_path(self):
    """The path to the main report file."""

    return os.path.join(self._json_dir, 'build.json')

  def open(self):
    """Implementation of Reporter callback."""

    safe_mkdir(os.path.dirname(self._json_dir))
    self._report_file = open(self.report_path(), 'w')

  def close(self):
    """Implementation of Reporter callback."""

    if os.path.exists(self._json_dir):
      self._report_file.write(json.dumps(
        {
          'workunits': self._results,
          'artifact_cache_stats': self.run_tracker.artifact_cache_stats.get_all(),
        }
      ))
      self._report_file.flush()
    self._report_file.close()

  def start_workunit(self, workunit):
    """Implementation of Reporter callback."""

    workunit_data = {
      'name': workunit.name,
      'id': str(workunit.id),
      'parent_name': workunit.parent.name if workunit.parent else '',
      'parent_id': str(workunit.parent.id) if workunit.parent else '',
      'labels': list(workunit.labels),
      'cmd': workunit.cmd or '',
      'start_time': workunit.start_time,
      'outputs': defaultdict(str),
      'children': [],
      'log_entries': [],
    }

    root_id = str(workunit.root().id)

    if not root_id in self._stack_per_thread:
      self._stack_per_thread[root_id].append(workunit_data)
      self._results[root_id] = workunit_data
    else:
      self._stack_per_thread[root_id][-1]['children'].append(workunit_data)
      self._stack_per_thread[root_id].append(workunit_data)

  def end_workunit(self, workunit):
    """Implementation of Reporter callback."""

    additional_data = {
      'outcome': workunit.outcome_string(workunit.outcome()),
      'end_time': workunit.end_time,
      'unaccounted_time': workunit.unaccounted_time(),
    }

    root_id = str(workunit.root().id)

    self._stack_per_thread[root_id][-1].update(additional_data)
    self._stack_per_thread[root_id].pop()

  def handle_output(self, workunit, label, stream):
    """Implementation of Reporter callback."""

    self._stack_per_thread[str(workunit.root().id)][-1]['outputs'][label] += stream

  def do_handle_log(self, workunit, level, *msg_elements):
    """Implementation of Reporter callback."""

    entry_info = {
      'level': self._log_level_str[level],
      'messages': self._render_messages(*msg_elements),
    }

    current_stack = self._stack_per_thread[str(workunit.root().id)]
    if current_stack:
      current_stack[-1]['log_entries'].append(entry_info)
    else:
      self._results[str(workunit.root().id)]['log_entries'].append(entry_info)

  def _render_messages(self, *msg_elements):
    def _message_details(element):
      if isinstance(element, string_types):
        element = [element]

      text, detail = (x or y for x, y in zip_longest(element, ('', None)))
      return {'text': text, 'detail': detail}

    return list(map(_message_details, msg_elements))
