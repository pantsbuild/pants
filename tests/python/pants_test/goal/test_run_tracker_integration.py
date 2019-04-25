# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os
from builtins import open

from pants.util.contextutil import temporary_file_path
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class RunTrackerIntegrationTest(PantsRunIntegrationTest):
  def test_stats_local_json_file_v1(self):
    with temporary_file_path() as tmpfile:
      pants_run = self.run_pants([
        'test',
        '--run-tracker-stats-local-json-file={}'.format(tmpfile),
        '--run-tracker-stats-version=1',
        '--run-tracker-stats-option-scopes-to-record=["GLOBAL", "GLOBAL^v2_ui", "compile.zinc^capture_classpath"]',
        'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
      ])
      self.assert_success(pants_run)

      with open(tmpfile, 'r') as fp:
        stats_json = json.load(fp)
        self.assertIn('outcomes', stats_json)
        self.assertEqual(stats_json['outcomes']['main:test'], 'SUCCESS')
        self.assertIn('artifact_cache_stats', stats_json)
        self.assertIn('run_info', stats_json)
        self.assertIn('self_timings', stats_json)
        self.assertIn('cumulative_timings', stats_json)
        self.assertIn('pantsd_stats', stats_json)
        self.assertIn('recorded_options', stats_json)
        self.assertIn('GLOBAL', stats_json['recorded_options'])
        self.assertIs(stats_json['recorded_options']['GLOBAL']['v2_ui'], False)
        self.assertEqual(stats_json['recorded_options']['GLOBAL']['level'], 'info')
        self.assertIs(stats_json['recorded_options']['GLOBAL^v2_ui'], False)
        self.assertEqual(stats_json['recorded_options']['compile.zinc^capture_classpath'], True)

  def test_stats_local_json_file_v2(self):
    with temporary_file_path() as tmpfile:
      pants_run = self.run_pants([
        'test',
        '--run-tracker-stats-local-json-file={}'.format(tmpfile),
        '--run-tracker-stats-version=2',
        'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
      ])
      self.assert_success(pants_run)

      with open(tmpfile, 'r') as fp:
        stats_json = json.load(fp)
        self.assertIn('artifact_cache_stats', stats_json)
        self.assertIn('run_info', stats_json)
        self.assertIn('pantsd_stats', stats_json)
        self.assertIn('workunits', stats_json)

  def test_workunit_failure(self):
    pants_run = self.run_pants([
      '--pythonpath={}'.format(os.path.join(os.getcwd(), 'tests', 'python')),
      '--backend-packages={}'.format('pants_test.goal.data'),
      'run-dummy-workunit',
      '--no-success'
    ])
    # Make sure the task actually happens and of no exception.
    self.assertIn('[run-dummy-workunit]', pants_run.stdout_data)
    self.assertNotIn('Exception', pants_run.stderr_data)
    self.assert_failure(pants_run)

  def test_workunit_success(self):
    pants_run = self.run_pants([
      '--pythonpath={}'.format(os.path.join(os.getcwd(), 'tests', 'python')),
      '--backend-packages={}'.format('pants_test.goal.data'),
      'run-dummy-workunit',
      '--success'
    ])
    self.assert_success(pants_run)
