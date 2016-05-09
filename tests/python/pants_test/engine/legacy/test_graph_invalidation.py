# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

import mock

from pants.bin.goal_runner import EngineInitializer


class GraphInvalidationTest(unittest.TestCase):
  def _make_setup_args(self, *specs):
    options = mock.Mock()
    options.target_specs = specs
    return dict(options=options)

  def setup_legacy_product_graph(self, *specs):
    kwargs = self._make_setup_args(*specs)
    with EngineInitializer.open_legacy_graph(**kwargs) as (_, _, scheduler):
      return scheduler.product_graph

  def test_invalidate_fsnode(self):
    product_graph = self.setup_legacy_product_graph('3rdparty/python::')

    initial_node_count = len(product_graph)
    self.assertGreater(initial_node_count, 0)

    product_graph.invalidate_files(['3rdparty/python/BUILD'])
    self.assertLess(len(product_graph), initial_node_count)

  def test_invalidate_fsnode_incremental(self):
    product_graph = self.setup_legacy_product_graph('3rdparty/python::')

    node_count = len(product_graph)
    self.assertGreater(node_count, 0)

    # Invalidate the '3rdparty/python' Path's DirectoryListing first by touching a random file.
    for filename in ('3rdparty/python/CHANGED_RANDOM_FILE', '3rdparty/python/BUILD'):
      product_graph.invalidate_files([filename])
      node_count, last_node_count = len(product_graph), node_count
      self.assertLess(node_count, last_node_count)
