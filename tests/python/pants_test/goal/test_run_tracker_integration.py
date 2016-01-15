# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json

from pants.util.contextutil import temporary_file_path
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class RunTrackerIntegrationTest(PantsRunIntegrationTest):
  def test_stats_local_json_file(self):
    with temporary_file_path() as tmpfile:
      pants_run = self.run_pants(['test',
                                  '--run-tracker-stats-local-json-file={}'.format(tmpfile),
                                  'testprojects/src/java/org/pantsbuild/testproject/unicode/main'])
      self.assert_success(pants_run)

      with open(tmpfile, 'r') as fp:
        stats_json = json.load(fp)
        self.assertIn('outcomes', stats_json)
        self.assertEqual(stats_json['outcomes']['main:test'], 'SUCCESS')
        self.assertIn('artifact_cache_stats', stats_json)
        self.assertIn('run_info', stats_json)
        self.assertIn('self_timings', stats_json)
        self.assertIn('cumulative_timings', stats_json)
