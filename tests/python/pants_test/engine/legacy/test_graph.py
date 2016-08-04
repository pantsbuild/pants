# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import contextmanager

import mock

from pants.bin.engine_initializer import EngineInitializer, LegacySymbolTable
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases, TargetMacro
from pants.build_graph.target import Target


class GraphInvalidationTest(unittest.TestCase):
  def _make_setup_args(self, specs, symbol_table_cls=None):
    options = mock.Mock()
    options.target_specs = specs
    return dict(options=options, symbol_table_cls=symbol_table_cls)

  @contextmanager
  def open_scheduler(self, specs, symbol_table_cls=None):
    kwargs = self._make_setup_args(specs, symbol_table_cls=symbol_table_cls)
    with EngineInitializer.open_legacy_graph(**kwargs) as triple:
      yield triple

  @contextmanager
  def open_pg(self, specs):
    with self.open_scheduler(specs) as (_, _, scheduler):
      yield scheduler.product_graph

  def test_invalidate_fsnode(self):
    with self.open_pg(['3rdparty/python::']) as product_graph:
      initial_node_count = len(product_graph)
      self.assertGreater(initial_node_count, 0)

      invalidated_count = product_graph.invalidate_files(['3rdparty/python/BUILD'])
      self.assertGreater(invalidated_count, 0)
      self.assertLess(len(product_graph), initial_node_count)

  def test_invalidate_fsnode_incremental(self):
    with self.open_pg(['3rdparty::']) as product_graph:
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
    with self.open_scheduler([spec]) as (graph, _, _):
      target = graph.get_target(Address.parse(spec))
      sources = [os.path.basename(s) for s in target.sources_relative_to_buildroot()]
      self.assertEquals(['p', 'a', 'n', 't', 's', 'b', 'u', 'i', 'l', 'd'],
                        sources)

  def test_target_macro_override(self):
    """Tests that we can "wrap" an existing target type with additional functionality.

    Installs an additional TargetMacro that wraps `target` aliases to add a tag to all definitions.
    """
    tag = 'tag_added_by_macro'
    target_cls = Target
    spec = 'testprojects/tests/python/pants/build_parsing:'

    # Macro that adds the specified tag.
    def macro(parse_context, tags=None, **kwargs):
      tags = tags or set()
      tags.add(tag)
      parse_context.create_object(target_cls, tags=tags, **kwargs)

    # SymbolTable that extends the legacy table to apply the macro.
    class TaggingSymbolTable(LegacySymbolTable):
      @classmethod
      def aliases(cls):
        return super(TaggingSymbolTable, cls).aliases().merge(
            BuildFileAliases(
              targets={'target': TargetMacro.Factory.wrap(macro, target_cls),}
            )
          )

    # Confirm that python_tests in a small directory are marked.
    with self.open_scheduler([spec], symbol_table_cls=TaggingSymbolTable) as (graph, addresses, _):
      self.assertTrue(len(addresses) > 0, 'No targets matched by {}'.format(addresses))
      for address in addresses:
        self.assertIn(tag, graph.get_target(address).tags)
