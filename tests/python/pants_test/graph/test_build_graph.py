# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import os
from textwrap import dedent

import pytest

from pants.base.address import SyntheticAddress
from pants.base.build_configuration import BuildConfiguration
from pants.base.build_file_parser import BuildFileParser
from pants.base.build_graph import BuildGraph
from pants.base.build_root import BuildRoot
from pants.base.target import Target
from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import touch


class BuildGraphTest(unittest.TestCase):
  @contextmanager
  def workspace(self, *buildfiles):
    with temporary_dir() as root_dir:
      with BuildRoot().temporary(root_dir):
        with pushd(root_dir):
          for buildfile in buildfiles:
            touch(os.path.join(root_dir, buildfile))
          yield os.path.realpath(root_dir)

  def test_transitive_closure_spec(self):
    with self.workspace('./BUILD', 'a/BUILD', 'a/b/BUILD') as root_dir:
      with open(os.path.join(root_dir, './BUILD'), 'w') as build:
        build.write(dedent('''
          fake(name="foo",
               dependencies=[
                 'a',
               ])
        '''))

      with open(os.path.join(root_dir, 'a/BUILD'), 'w') as build:
        build.write(dedent('''
          fake(name="a",
               dependencies=[
                 'a/b:bat',
               ])
        '''))

      with open(os.path.join(root_dir, 'a/b/BUILD'), 'w') as build:
        build.write(dedent('''
          fake(name="bat")
        '''))

      build_configuration = BuildConfiguration()
      build_configuration.register_target_alias('fake', Target)
      parser = BuildFileParser(build_configuration, root_dir=root_dir)
      build_graph = BuildGraph(self.address_mapper)
      parser.inject_spec_closure_into_build_graph(':foo', build_graph)
      self.assertEqual(len(build_graph.dependencies_of(SyntheticAddress.parse(':foo'))), 1)

  def test_target_invalid(self):
    self.add_to_build_file('a/BUILD', 'dependencies(name="a")')
    with pytest.raises(BuildFileParser.InvalidTargetException):
      self.build_graph.inject_spec_closure('a:nope')

    self.add_to_build_file('b/BUILD', 'dependencies(name="a")')
    with pytest.raises(BuildFileParser.InvalidTargetException):
      self.build_graph.inject_spec_closure('b')
    with pytest.raises(BuildFileParser.InvalidTargetException):
      self.build_graph.inject_spec_closure('b:b')
    with pytest.raises(BuildFileParser.InvalidTargetException):
      self.build_graph.inject_spec_closure('b:')

  def test_transitive_closure_address(self):
    with self.workspace('./BUILD', 'a/BUILD', 'a/b/BUILD') as root_dir:
      with open(os.path.join(root_dir, './BUILD'), 'w') as build:
        build.write(dedent('''
          fake(name="foo",
               dependencies=[
                 'a',
               ])
        '''))

      with open(os.path.join(root_dir, 'a/BUILD'), 'w') as build:
        build.write(dedent('''
          fake(name="a",
               dependencies=[
                 'a/b:bat',
               ])
        '''))

      with open(os.path.join(root_dir, 'a/b/BUILD'), 'w') as build:
        build.write(dedent('''
          fake(name="bat")
        '''))
      def fake_target(*args, **kwargs):
        assert False, "This fake target should never be called in this test!"

      alias_map = {'target_aliases': {'fake': fake_target}}
      self.build_file_parser.register_alias_groups(alias_map=alias_map)

      bf_address = BuildFileAddress(BuildFile(root_dir, 'BUILD'), 'foo')
      self.build_file_parser._populate_target_proxy_transitive_closure_for_address(bf_address)
      self.assertEqual(len(self.build_file_parser._target_proxy_by_address), 3)

  def test_no_targets(self):
    self.add_to_build_file('empty/BUILD', 'pass')
    with pytest.raises(BuildFileParser.EmptyBuildFileException):
      self.build_file_parser.inject_spec_closure_into_build_graph('empty', self.build_graph)
    with pytest.raises(BuildFileParser.EmptyBuildFileException):
      self.build_file_parser.inject_spec_closure_into_build_graph('empty:foo', self.build_graph)

