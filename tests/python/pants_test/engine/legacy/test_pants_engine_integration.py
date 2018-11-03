# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from future.utils import PY3

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PantsEngineIntegrationTest(PantsRunIntegrationTest):
  def test_engine_list(self):
    pants_run = self.run_pants(['-ldebug', 'list', '3rdparty::'])
    self.assert_success(pants_run)
    self.assertRegexpMatches(pants_run.stderr_data, 'build_graph is: .*LegacyBuildGraph')
    self.assertRegexpMatches(pants_run.stderr_data,
                             'computed \d+ nodes in')
    if PY3:
      self.assertNotRegex(pants_run.stderr_data, 'pantsd is running at pid \d+')
    else:
      self.assertNotRegexpMatches(pants_run.stderr_data, 'pantsd is running at pid \d+')

  def test_engine_binary(self):
    self.assert_success(
      self.run_pants(
        ['binary', 'examples/src/python/example/hello/main:']
      )
    )
