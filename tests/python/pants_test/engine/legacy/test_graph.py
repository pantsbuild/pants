# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import os
import unittest
from contextlib import contextmanager

import mock

from pants.bin.engine_initializer import EngineInitializer, LegacySymbolTable
from pants.bin.target_roots import TargetRoots
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases, TargetMacro
from pants.build_graph.target import Target
from pants_test.engine.util import init_native


# Macro that adds the specified tag.
def macro(target_cls, tag, parse_context, tags=None, **kwargs):
  tags = tags or set()
  tags.add(tag)
  parse_context.create_object(target_cls, tags=tags, **kwargs)


# SymbolTable that extends the legacy table to apply the macro.
class TaggingSymbolTable(LegacySymbolTable):
  tag = 'tag_added_by_macro'
  target_cls = Target

  @classmethod
  def aliases(cls):
    tag_macro = functools.partial(macro, cls.target_cls, cls.tag)
    return super(TaggingSymbolTable, cls).aliases().merge(
        BuildFileAliases(
          targets={'target': TargetMacro.Factory.wrap(tag_macro, cls.target_cls),}
        )
      )


class GraphInvalidationTest(unittest.TestCase):

  _native = init_native()

  def _make_setup_args(self, specs):
    options = mock.Mock()
    options.target_specs = specs
    return options

  @contextmanager
  def open_scheduler(self, specs, symbol_table_cls=None):
    path_ignore_patterns = ['.*']
    target_roots = TargetRoots.create(options=self._make_setup_args(specs))
    graph_helper = EngineInitializer.setup_legacy_graph(path_ignore_patterns,
                                                        symbol_table_cls=symbol_table_cls,
                                                        native=self._native)
    graph = graph_helper.create_build_graph(target_roots)[0]
    addresses = tuple(graph.inject_specs_closure(target_roots.as_specs()))
    yield graph, addresses, graph_helper.scheduler

  def test_invalidate_fsnode(self):
    with self.open_scheduler(['3rdparty/python::']) as (_, _, scheduler):
      initial_node_count = scheduler.node_count()
      self.assertGreater(initial_node_count, 0)

      invalidated_count = scheduler.invalidate_files(['3rdparty/python/BUILD'])
      self.assertGreater(invalidated_count, 0)
      self.assertLess(scheduler.node_count(), initial_node_count)

  def test_invalidate_fsnode_incremental(self):
    with self.open_scheduler(['//:', '3rdparty/::']) as (_, _, scheduler):
      node_count = scheduler.node_count()
      self.assertGreater(node_count, 0)

      # Invalidate the '3rdparty/python' DirectoryListing, the `3rdparty` DirectoryListing,
      # and then the root DirectoryListing by "touching" files/dirs.
      # NB: Invalidation of entries in the root directory is special: because Watchman will
      # never trigger an event for the root itself, we treat changes to files in the root
      # directory as events for the root.
      for filename in ('3rdparty/python/BUILD', '3rdparty/python', 'non_existing_file'):
        invalidated_count = scheduler.invalidate_files([filename])
        self.assertGreater(invalidated_count,
                           0,
                           'File {} did not invalidate any Nodes.'.format(filename))
        node_count, last_node_count = scheduler.node_count(), node_count
        self.assertLess(node_count, last_node_count)

  def test_sources_ordering(self):
    spec = 'testprojects/src/resources/org/pantsbuild/testproject/ordering'
    with self.open_scheduler([spec]) as (graph, _, _):
      target = graph.get_target(Address.parse(spec))
      sources = [os.path.basename(s) for s in target.sources_relative_to_buildroot()]
      self.assertEquals(['p', 'a', 'n', 't', 's', 'b', 'u', 'i', 'l', 'd'],
                        sources)

  def test_implicit_sources(self):
    expected_sources = {
      'testprojects/tests/python/pants/file_sets:implicit_sources':
        ['a.py', 'aa.py', 'aaa.py', 'aabb.py', 'ab.py'],
      'testprojects/tests/python/pants/file_sets:test_with_implicit_sources':
        ['test_a.py']
    }

    for spec, exp_sources in expected_sources.items():
      with self.open_scheduler([spec]) as (graph, _, _):
        target = graph.get_target(Address.parse(spec))
        sources = sorted([os.path.basename(s) for s in target.sources_relative_to_buildroot()])
        self.assertEquals(exp_sources, sources)

  def test_target_macro_override(self):
    """Tests that we can "wrap" an existing target type with additional functionality.

    Installs an additional TargetMacro that wraps `target` aliases to add a tag to all definitions.
    """
    spec = 'testprojects/tests/python/pants/build_parsing:'

    # Confirm that python_tests in a small directory are marked.
    with self.open_scheduler([spec], symbol_table_cls=TaggingSymbolTable) as (graph, addresses, _):
      self.assertTrue(len(addresses) > 0, 'No targets matched by {}'.format(addresses))
      for address in addresses:
        self.assertIn(TaggingSymbolTable.tag, graph.get_target(address).tags)
