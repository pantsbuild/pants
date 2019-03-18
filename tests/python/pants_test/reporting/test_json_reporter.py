# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json

from pants.base.workunit import WorkUnit
from pants.reporting.report import Report
from pants.reporting.reporting import JsonReporter
from pants.util.contextutil import temporary_dir
from pants_test.test_base import TestBase


class FakeRunTracker(object):

  class FakeCacheStats(object):
    def get_all(self):
      return []

  artifact_cache_stats = FakeCacheStats()


class FakeWorkUnit(object):
  def __init__(self, parent, **kwargs):
    self.name = kwargs['name']
    self.id = '{}_id'.format(self.name)
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

  def outcome(self):
    return WorkUnit.SUCCESS

  def outcome_string(self, outcome):
    return WorkUnit.outcome_string(outcome)


def generate_callbacks(workunit_data, reporter, parent=None):
  workunit = FakeWorkUnit(parent, **workunit_data)
  reporter.start_workunit(workunit)
  for child_workunit in workunit_data['children']:
    generate_callbacks(child_workunit, reporter, workunit)
  reporter.end_workunit(workunit)


class JsonReporterTest(TestBase):

  def _check_callbacks(self, root_workunit_dict, reporter):
    reporter.open()
    generate_callbacks(root_workunit_dict, reporter)
    reporter.close()
    result = json.loads(open(reporter.report_path).read())
    self.assertDictEqual(root_workunit_dict, result['workunits'][root_workunit_dict['id']])

  def test_nested_grandchild(self):
    expected = {
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
    }

    with temporary_dir() as temp_dir:
      reporter = JsonReporter(FakeRunTracker(),
        JsonReporter.Settings(log_level=Report.INFO, json_dir=temp_dir))

      self._check_callbacks(expected, reporter)

  def test_nested_great_grandchilden(self):
    expected = {
      'name': 'root',
      'id': 'root_id',
      'parent_name': '',
      'parent_id': '',
      'labels': [],
      'cmd': '',
      'start_time': -5419800.0,
      'outputs': {},
      'children': [
        {
          'name': 'child',
          'id': 'child_id',
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
              'parent_name': 'child',
              'parent_id': 'child_id',
              'labels': [
                'LABEL1'
              ],
              'cmd': '',
              'start_time': 479721600.0,
              'outputs': {},
              'children': [
                {
                  'name': 'great_grandchild1',
                  'id': 'great_grandchild1_id',
                  'parent_name': 'grandchild',
                  'parent_id': 'grandchild_id',
                  'labels': [],
                  'cmd': '',
                  'start_time': 684140400.0,
                  'outputs': {},
                  'children': [],
                  'log_entries': [],
                  'outcome': 'SUCCESS',
                  'end_time': 684140410.0,
                  'unaccounted_time': 0
                },
                {
                  'name': 'great_grandchild2',
                  'id': 'great_grandchild2_id',
                  'parent_name': 'grandchild',
                  'parent_id': 'grandchild_id',
                  'labels': [
                    'TURTLES'
                  ],
                  'cmd': '',
                  'start_time': 1234.0,
                  'outputs': {},
                  'children': [],
                  'log_entries': [],
                  'outcome': 'SUCCESS',
                  'end_time': 1244.0,
                  'unaccounted_time': 0
                }
              ],
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
      ],
      'log_entries': [],
      'outcome': 'SUCCESS',
      'end_time': -5419790.0,
      'unaccounted_time': 0
    }

    with temporary_dir() as temp_dir:
      reporter = JsonReporter(FakeRunTracker(),
        JsonReporter.Settings(log_level=Report.INFO, json_dir=temp_dir))

      self._check_callbacks(expected, reporter)
