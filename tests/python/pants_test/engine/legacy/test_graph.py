# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import contextmanager

import mock

from pants.bin.goal_runner import EngineInitializer
from pants.build_graph.address import Address


class GraphInvalidationTest(unittest.TestCase):
  def _make_setup_args(self, *specs):
    options = mock.Mock()
    options.target_specs = specs
    return dict(options=options)

  @contextmanager
  def open_scheduler(self, *specs):
    kwargs = self._make_setup_args(*specs)
    with EngineInitializer.open_legacy_graph(**kwargs) as triple:
      yield triple

  @contextmanager
  def open_pg(self, *specs):
    with self.open_scheduler(*specs) as (_, _, scheduler):
      yield scheduler.product_graph

  def test_invalidate_fsnode(self):
    with self.open_pg('3rdparty/python::') as product_graph:
      initial_node_count = len(product_graph)
      self.assertGreater(initial_node_count, 0)

      invalidated_count = product_graph.invalidate_files(['3rdparty/python/BUILD'])
      self.assertGreater(invalidated_count, 0)
      self.assertLess(len(product_graph), initial_node_count)

  def test_invalidate_fsnode_incremental(self):
    with self.open_pg('3rdparty::') as product_graph:
      node_count = len(product_graph)
      self.assertGreater(node_count, 0)

      # Invalidate the '3rdparty/python' DirectoryListing, and then the `3rdparty` DirectoryListing.
      # by "touching" random files.
      for filename in ('3rdparty/python/BUILD', '3rdparty/CHANGED_RANDOM_FILE'):
        invalidated_count = product_graph.invalidate_files([filename])
        self.assertGreater(invalidated_count, 0)
        node_count, last_node_count = len(product_graph), node_count
        self.assertLess(node_count, last_node_count)

  def test_sources_ordering(self):
    spec = 'testprojects/src/resources/org/pantsbuild/testproject/ordering'
    with self.open_scheduler(spec) as (graph, _, _):
      target = graph.get_target(Address.parse(spec))
      sources = [os.path.basename(s) for s in target.sources_relative_to_buildroot()]
      self.assertEquals(['p', 'a', 'n', 't', 's', 'b', 'u', 'i', 'l', 'd', 'p', 'a', 'n', 't', 's'],
                        sources)
