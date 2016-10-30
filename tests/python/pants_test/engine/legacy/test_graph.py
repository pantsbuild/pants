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
from pants.engine.subsystem.native import Native


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


@contextmanager
def open_legacy_graph(options=None, path_ignore_patterns=None, symbol_table_cls=None):
  """A context manager that yields a usable, legacy LegacyBuildGraph by way of the v2 scheduler.

  :param Options options: An Options object to use for this run.
  :param list path_ignore_patterns: A list of path ignore patterns for FileSystemProjectTree,
                                    usually taken from the `--pants-ignore` global option.
                                    Defaults to: ['.*']
  :param SymbolTable symbol_table_cls: A SymbolTable class to use for build file parsing, or
                                       None to use the default.
  :yields: A tuple of (graph, addresses, scheduler).
  """
  path_ignore_patterns = path_ignore_patterns or ['.*']
  target_roots = TargetRoots.create(options=options)
  native = Native.Factory.global_instance().create()
  graph_helper = EngineInitializer.setup_legacy_graph(path_ignore_patterns,
                                                      symbol_table_cls=symbol_table_cls,
                                                      native=native)
  try:
    graph = graph_helper.create_build_graph(target_roots)[0]
    addresses = tuple(graph.inject_specs_closure(target_roots.as_specs()))
    yield graph, addresses, graph_helper.scheduler
  finally:
    graph_helper.engine.close()


class GraphInvalidationTest(unittest.TestCase):
  def _make_setup_args(self, specs, **kwargs):
    options = mock.Mock()
    options.target_specs = specs
    kwargs['options'] = options
    return kwargs

  @contextmanager
  def open_scheduler(self, specs, symbol_table_cls=None):
    kwargs = self._make_setup_args(specs, symbol_table_cls=symbol_table_cls)
    with open_legacy_graph(**kwargs) as triple:
      yield triple

  def test_invalidate_fsnode(self):
    with self.open_scheduler(['3rdparty/python::']) as (_, _, scheduler):
      initial_node_count = len(scheduler.product_graph)
      self.assertGreater(initial_node_count, 0)

      invalidated_count = scheduler.invalidate_files(['3rdparty/python/BUILD'])
      self.assertGreater(invalidated_count, 0)
      self.assertLess(len(scheduler.product_graph), initial_node_count)

  def test_invalidate_fsnode_incremental(self):
    with self.open_scheduler(['//:', '3rdparty/::']) as (graph, _, _):
      node_count = len(graph)
      self.assertGreater(node_count, 0)

      # Invalidate the '3rdparty/python' DirectoryListing, the `3rdparty` DirectoryListing,
      # and then the root DirectoryListing by "touching" files/dirs.
      for filename in ('3rdparty/python/BUILD', '3rdparty/python', 'non_existing_file'):
        invalidated_count = graph.invalidate_files([filename])
        self.assertGreater(invalidated_count,
                           0,
                           'File {} did not invalidate any Nodes.'.format(filename))
        node_count, last_node_count = len(graph), node_count
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
    spec = 'testprojects/tests/python/pants/build_parsing:'

    # Confirm that python_tests in a small directory are marked.
    with self.open_scheduler([spec], symbol_table_cls=TaggingSymbolTable) as (graph, addresses, _):
      self.assertTrue(len(addresses) > 0, 'No targets matched by {}'.format(addresses))
      for address in addresses:
        self.assertIn(TaggingSymbolTable.tag, graph.get_target(address).tags)
