# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os
from contextlib import contextmanager

from pants.base.workunit import WorkUnit
from pants.reporting.report import Report
from pants.reporting.reporting import JsonReporter
from pants.util.contextutil import temporary_dir
from pants_test.test_base import TestBase


class FakeRunTracker(object):
  reporter = None

  class FakeCacheStats(object):
    def get_all(self):
      return []

  def __init__(self):
    self.artifact_cache_stats = self.FakeCacheStats()

  def start(self):
    self.reporter.open()

  def end(self):
    self.reporter.close()

  @contextmanager
  def new_workunit(self, workunit):
    self.reporter.start_workunit(workunit)
    yield workunit
    self.reporter.end_workunit(workunit)


class FakeWorkUnit(object):
  def __init__(self, parent, name, **kwargs):
    self.name = name
    self.id = '{}_id'.format(name)
    self.parent = parent
    self.cmd = ''
    self.labels = kwargs.get('labels', [])
    self.start_time = kwargs.get('start_time', 8675309.0)
    self.end_time = self.start_time + 10

  def unaccounted_time(self):
    return 0

  def root(self):
    ret = self
    while ret.parent is not None:
      ret = ret.parent
    return ret

  def outputs(self):
    return {}

  def outcome(self):
    return WorkUnit.SUCCESS

  def outcome_string(self, outcome):
    return WorkUnit.outcome_string(outcome)


class JsonReporterTest(TestBase):

  def test_reporter_output(self):
    expected = {
      'workunits': {
        'root_id': {
          'name': 'root',
          'id': 'root_id',
          'parent_name': '',
          'parent_id': '',
          'labels': [
            'IAMROOT'
          ],
          'cmd': '',
          'start_time': -5419800.0,
          'outputs': {},
          'children': [
            {
              'name': 'child1',
              'id': 'child1_id',
              'parent_name': 'root',
              'parent_id': 'root_id',
              'labels': [],
              'cmd': '',
              'start_time': 31564800.0,
              'outputs': {},
              'children': [
                {
                  'name': 'grandchild',
                  'id': 'grandchild_id',
                  'parent_name': 'child1',
                  'parent_id': 'child1_id',
                  'labels': [
                    'LABEL1'
                  ],
                  'cmd': '',
                  'start_time': 479721600.0,
                  'outputs': {},
                  'children': [],
                  'log_entries': [],
                  'outcome': 'SUCCESS',
                  'end_time': 479721610.0,
                  'unaccounted_time': 0
                }
              ],
              'log_entries': [],
              'outcome': 'SUCCESS',
              'end_time': 31564810.0,
              'unaccounted_time': 0
            },
            {
              'name': 'child2',
              'id': 'child2_id',
              'parent_name': 'root',
              'parent_id': 'root_id',
              'labels': [],
              'cmd': '',
              'start_time': 684140400.0,
              'outputs': {},
              'children': [],
              'log_entries': [],
              'outcome': 'SUCCESS',
              'end_time': 684140410.0,
              'unaccounted_time': 0
            }
          ],
          'log_entries': [],
          'outcome': 'SUCCESS',
          'end_time': -5419790.0,
          'unaccounted_time': 0
        },
      },
      'artifact_cache_stats': []
    }

    with temporary_dir() as temp_dir:
      run_tracker = FakeRunTracker()
      reporter = JsonReporter(run_tracker, JsonReporter.Settings(log_level=Report.INFO, json_dir=temp_dir))
      run_tracker.reporter = reporter

      run_tracker.start()

      with run_tracker.new_workunit(FakeWorkUnit(None, 'root', labels=['IAMROOT'], start_time=-5419800.0)) as root_workunit:
        with run_tracker.new_workunit(FakeWorkUnit(root_workunit, 'child1', start_time=31564800.0)) as child1:
          with run_tracker.new_workunit(FakeWorkUnit(child1, 'grandchild', labels=['LABEL1'], start_time=479721600.0)): pass
        with run_tracker.new_workunit(FakeWorkUnit(root_workunit, 'child2', start_time=684140400.0)): pass

      run_tracker.end()

      result = json.loads(open(os.path.join(reporter.report_path())).read())
      self.assertDictEqual(expected, result)
