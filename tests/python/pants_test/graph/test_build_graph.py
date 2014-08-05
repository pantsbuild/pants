# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import os
import sys
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
from pants_test.base_test import BaseTest

# TODO(Eric Ayers) There are many untested methods in BuildGraph left to be tested.

class BuildGraphTest(BaseTest):

  @contextmanager
  def workspace(self, *buildfiles):
    with temporary_dir() as root_dir:
      with BuildRoot().temporary(root_dir):
        with pushd(root_dir):
          for buildfile in buildfiles:
            touch(os.path.join(root_dir, buildfile))
          yield os.path.realpath(root_dir)

  # TODO(Eric Ayers) This test broke during a refactoring and should be moved, removed or updated
  @pytest.mark.xfail
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

  # TODO(Eric Ayers) This test broke during a refactoring and should be moved, removed or updated
  @pytest.mark.xfail
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

  # TODO(Eric Ayers) This test broke during a refactoring and should be moved removed or updated
  @pytest.mark.xfail
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

  # TODO(Eric Ayers) This test broke during a refactoring and should be moved, removed or updated
  @pytest.mark.xfail
  def test_no_targets(self):
    self.add_to_build_file('empty/BUILD', 'pass')
    with pytest.raises(BuildFileParser.EmptyBuildFileException):
      self.build_file_parser.inject_spec_closure_into_build_graph('empty', self.build_graph)
    with pytest.raises(BuildFileParser.EmptyBuildFileException):
      self.build_file_parser.inject_spec_closure_into_build_graph('empty:foo', self.build_graph)

  def test_contains_address(self):
    a = SyntheticAddress.parse('a')
    self.assertFalse(self.build_graph.contains_address(a))
    target = Target(name='a',
                    address=a,
                    build_graph=self.build_graph)
    self.build_graph.inject_target(target)
    self.assertTrue(self.build_graph.contains_address(a))

  def test_get_target_from_spec(self):
    a = self.make_target('foo:a')
    result = self.build_graph.get_target_from_spec('foo:a')
    self.assertEquals(a, result)
    b = self.make_target('foo:b')
    result = self.build_graph.get_target_from_spec(':b', relative_to='foo')
    self.assertEquals(b, result)

  def test_walk_graph(self):
    """
    Make sure that BuildGraph.walk_transitive_dependency_graph() and
    BuildGraph.walk_transitive_dependee_graph() return DFS inorder traversal.
    """
    def assertDependencyWalk(target, results):
      targets = []
      self.build_graph.walk_transitive_dependency_graph([target.address],
                                                         lambda x: targets.append(x))
      self.assertEquals(results, targets)

    def assertDependeeWalk(target, results):
      targets = []
      self.build_graph.walk_transitive_dependee_graph([target.address],
                                                        lambda x: targets.append(x))
      self.assertEquals(results, targets)

    a = self.make_target('a')
    b = self.make_target('b', dependencies=[a])
    c = self.make_target('c', dependencies=[b])
    d = self.make_target('d', dependencies=[c, a])
    e = self.make_target('e', dependencies=[d])

    assertDependencyWalk(a, [a])
    assertDependencyWalk(b, [b, a])
    assertDependencyWalk(c, [c, b , a])
    assertDependencyWalk(d, [d, c, b, a])
    assertDependencyWalk(e, [e, d, c, b, a])

    assertDependeeWalk(a, [a, b, c, d, e])
    assertDependeeWalk(b, [b, c, d, e])
    assertDependeeWalk(c, [c, d, e])
    assertDependeeWalk(d, [d, e])
    assertDependeeWalk(e, [e])

  def test_target_closure(self):
    a = self.make_target('a')
    self.assertEquals([a], a.closure())
    b = self.make_target('b', dependencies=[a])
    self.assertEquals([b, a], b.closure())
    c = self.make_target('c', dependencies=[b])
    self.assertEquals([c, b, a], c.closure())
    d = self.make_target('d', dependencies=[a, c])
    self.assertEquals([d, a, c, b], d.closure())

  def test_target_walk(self):
    def assertWalk(expected, target):
      results = []
      target.walk(lambda x: results.append(x))
      self.assertEquals(expected, results)

    a = self.make_target('a')
    assertWalk([a], a)
    b = self.make_target('b', dependencies=[a])
    assertWalk([b, a], b)
    c = self.make_target('c', dependencies=[b])
    assertWalk([c, b, a], c)
    d = self.make_target('d', dependencies=[a, c])
    assertWalk([d, a, c, b], d)

