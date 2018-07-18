# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import functools
import os
import unittest
from builtins import str
from contextlib import contextmanager

import mock

from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_file_aliases import BuildFileAliases, TargetMacro
from pants.build_graph.target import Target
from pants.init.engine_initializer import EngineInitializer
from pants.init.options_initializer import BuildConfigInitializer
from pants.init.target_roots_calculator import TargetRootsCalculator
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_dir
from pants_test.engine.util import init_native


# Macro that adds the specified tag.
def macro(target_cls, tag, parse_context, tags=None, **kwargs):
  tags = tags or set()
  tags.add(tag)
  parse_context.create_object(target_cls, tags=tags, **kwargs)


class GraphTestBase(unittest.TestCase):

  _native = init_native()

  def _make_setup_args(self, specs):
    options = mock.Mock(target_specs=specs)
    options.for_scope.return_value = mock.Mock(diffspec=None, changes_since=None)
    options.for_global_scope.return_value = mock.Mock(owner_of=None)
    return options

  def _default_build_config(self, build_file_aliases=None):
    # TODO: Get default BuildFileAliases by extending BaseTest post
    #   https://github.com/pantsbuild/pants/issues/4401
    build_config = BuildConfigInitializer.get(OptionsBootstrapper())
    if build_file_aliases:
      build_config.register_aliases(build_file_aliases)
    return build_config

  @contextmanager
  def graph_helper(self,
                   build_configuration=None,
                   build_file_imports_behavior='allow',
                   include_trace_on_error=True,
                   path_ignore_patterns=None):

    with temporary_dir() as work_dir:
      path_ignore_patterns = path_ignore_patterns or []
      build_config = build_configuration or self._default_build_config()
      # TODO: This test should be swapped to using TestBase.
      graph_helper = EngineInitializer.setup_legacy_graph_extended(
        path_ignore_patterns,
        work_dir,
        build_file_imports_behavior,
        build_configuration=build_config,
        native=self._native,
        include_trace_on_error=include_trace_on_error
      )
      yield graph_helper

  @contextmanager
  def open_scheduler(self, specs, build_configuration=None):
    with self.graph_helper(build_configuration=build_configuration) as graph_helper:
      graph, target_roots = self.create_graph_from_specs(graph_helper, specs)
      addresses = tuple(graph.inject_roots_closure(target_roots))
      yield graph, addresses, graph_helper.scheduler.new_session()

  def create_graph_from_specs(self, graph_helper, specs):
    Subsystem.reset()
    session = graph_helper.new_session()
    target_roots = self.create_target_roots(specs, session, session.symbol_table)
    graph = session.create_build_graph(target_roots)[0]
    return graph, target_roots

  def create_target_roots(self, specs, session, symbol_table):
    return TargetRootsCalculator.create(self._make_setup_args(specs), session, symbol_table)


class GraphTargetScanFailureTests(GraphTestBase):

  def test_with_missing_target_in_existing_build_file(self):
    # When a target is missing,
    #  the suggestions should be in order
    #  and there should only be one copy of the error if tracing is off.
    with self.assertRaises(AddressLookupError) as cm:
      with self.graph_helper(include_trace_on_error=False) as graph_helper:
        self.create_graph_from_specs(graph_helper, ['3rdparty/python:rutabaga'])
        self.fail('Expected an exception.')

    error_message = str(cm.exception)
    expected_message = '"rutabaga" was not found in namespace "3rdparty/python".' \
                       ' Did you mean one of:\n' \
                       '  :Markdown\n' \
                       '  :Pygments\n'
    self.assertIn(expected_message, error_message)
    self.assertTrue(error_message.count(expected_message) == 1)

  def test_with_missing_directory_fails(self):
    with self.assertRaises(AddressLookupError) as cm:
      with self.graph_helper() as graph_helper:
        self.create_graph_from_specs(graph_helper, ['no-such-path:'])

    self.assertIn('Path "no-such-path" does not contain any BUILD files',
                  str(cm.exception))

  def test_with_existing_directory_with_no_build_files_fails(self):
    with self.assertRaises(AddressLookupError) as cm:
      path_ignore_patterns=[
        # This is a symlink that points out of the build root.
        '/build-support/bin/native/src'
      ]
      with self.graph_helper(path_ignore_patterns=path_ignore_patterns) as graph_helper:
        self.create_graph_from_specs(graph_helper, ['build-support/bin::'])

    self.assertIn('does not match any targets.', str(cm.exception))

  def test_inject_bad_dir(self):
    with self.assertRaises(AddressLookupError) as cm:
      with self.graph_helper() as graph_helper:
        graph, target_roots = self.create_graph_from_specs(graph_helper, ['3rdparty/python:'])

        graph.inject_address_closure(Address('build-support/bin', 'wat'))

    self.assertIn('Path "build-support/bin" does not contain any BUILD files',
                  str(cm.exception))


class GraphInvalidationTest(GraphTestBase):

  def test_invalidate_fsnode(self):
    # NB: Invalidation is now more directly tested in unit tests in the `graph` crate.
    with self.open_scheduler(['3rdparty/python::']) as (_, _, scheduler):
      invalidated_count = scheduler.invalidate_files(['3rdparty/python/BUILD'])
      self.assertGreater(invalidated_count, 0)

  def test_invalidate_fsnode_incremental(self):
    # NB: Invalidation is now more directly tested in unit tests in the `graph` crate.
    with self.open_scheduler(['//:', '3rdparty/::']) as (_, _, scheduler):
      # Invalidate the '3rdparty/python' DirectoryListing, the `3rdparty` DirectoryListing,
      # and then the root DirectoryListing by "touching" files/dirs.
      for filename in ('3rdparty/python/BUILD', '3rdparty/jvm', 'non_existing_file'):
        invalidated_count = scheduler.invalidate_files([filename])
        self.assertGreater(invalidated_count,
                           0,
                           'File {} did not invalidate any Nodes.'.format(filename))

  def _ordering_test(self, spec, expected_sources=None):
    expected_sources = expected_sources or ['p', 'a', 'n', 't', 's', 'b', 'u', 'i', 'l', 'd']
    with self.open_scheduler([spec]) as (graph, _, _):
      target = graph.get_target(Address.parse(spec))
      sources = [os.path.basename(s) for s in target.sources_relative_to_buildroot()]
      self.assertEquals(expected_sources, sources)

  def test_sources_ordering_literal(self):
    self._ordering_test('testprojects/src/resources/org/pantsbuild/testproject/ordering:literal')

  def test_sources_ordering_glob(self):
    self._ordering_test('testprojects/src/resources/org/pantsbuild/testproject/ordering:globs')

  def test_target_macro_override(self):
    """Tests that we can "wrap" an existing target type with additional functionality.

    Installs an additional TargetMacro that wraps `target` aliases to add a tag to all definitions.
    """
    spec = 'testprojects/tests/python/pants/build_parsing:'

    tag = 'tag_added_by_macro'
    target_cls = Target
    tag_macro = functools.partial(macro, target_cls, tag)
    target_symbols = {'target': TargetMacro.Factory.wrap(tag_macro, target_cls)}

    build_config = self._default_build_config(BuildFileAliases(targets=target_symbols))

    # Confirm that python_tests in a small directory are marked.
    with self.open_scheduler([spec], build_configuration=build_config) as (graph, addresses, _):
      self.assertTrue(len(addresses) > 0, 'No targets matched by {}'.format(addresses))
      for address in addresses:
        self.assertIn(tag, graph.get_target(address).tags)
