# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestJvmDependencyUsageIntegration(PantsRunIntegrationTest):
  """Simple coverage tests of the two output modes."""

  def test_simple_dep_usage_graph(self):
    self.assert_success(
        self.run_pants(['dep-usage.jvm', '--summary', 'examples/src/scala/org/pantsbuild/example::']))

  def test_dep_usage_graph_with_synthetic_targets(self):
    self.assert_success(
        self.run_pants(['dep-usage.jvm', '--no-summary', 'examples/src/scala/org/pantsbuild/example::']))
