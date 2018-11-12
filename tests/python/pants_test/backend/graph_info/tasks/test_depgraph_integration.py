# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class DepgraphIntegrationTest(PantsRunIntegrationTest):
  def test_depgraph(self):
    pants_run = self.run_pants([
      'depgraph',
      'testprojects/src/python/sources',
    ])
    self.assert_success(pants_run)
    self.assertEqual(pants_run.stdout_data, """digraph dependencies {
  "testprojects/src/python/sources" -> "testprojects/src/python/sources:text";
}
""")
