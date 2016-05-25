# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PantsEngineIntegrationTest(PantsRunIntegrationTest):
  def test_list_enable_engine(self):
    pants_run = self.run_pants(['-ldebug', '--enable-engine', 'list', '3rdparty::'])
    self.assert_success(pants_run)
    self.assertRegexpMatches(pants_run.stderr_data, 'build_graph is: .*LegacyBuildGraph')
    self.assertRegexpMatches(pants_run.stderr_data, 'ran \d+ scheduling iterations in')

  def test_list_all(self):
    self.assert_success(self.run_pants(['--enable-engine', 'list', '::']))
