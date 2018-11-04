# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.py2_compat import assertNotRegex, assertRegex


class PantsEngineIntegrationTest(PantsRunIntegrationTest):
  def test_engine_list(self):
    pants_run = self.run_pants(['-ldebug', 'list', '3rdparty::'])
    self.assert_success(pants_run)
    assertRegex(self, pants_run.stderr_data, 'build_graph is: .*LegacyBuildGraph')
    assertRegex(self, pants_run.stderr_data,
                             'computed \d+ nodes in')
    assertNotRegex(self, pants_run.stderr_data, 'pantsd is running at pid \d+')

  def test_engine_binary(self):
    self.assert_success(
      self.run_pants(
        ['binary', 'examples/src/python/example/hello/main:']
      )
    )
