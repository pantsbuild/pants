# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.graph_info.tasks.minimal_cover import MinimalCover
from pants.backend.python.targets.python_library import PythonLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class BaseMinimalCovertTest(ConsoleTaskTestBase):
  @classmethod
  def task_type(cls):
    return MinimalCover


class MinimalCoverEmptyTest(BaseMinimalCovertTest):
  def test(self):
    self.assert_console_output(targets=[])


class MinimalCoverTest(BaseMinimalCovertTest):
  @property
  def alias_groups(self):
    return BuildFileAliases(targets={'python_library': PythonLibrary})

  def setUp(self):
    super(MinimalCoverTest, self).setUp()

    def add_to_build_file(path, name, *deps):
      all_deps = ["'{0}'".format(dep) for dep in list(deps)]
      self.add_to_build_file(path, dedent("""
          python_library(name='{name}',
            sources=[],
            dependencies=[{all_deps}]
          )
          """.format(name=name, all_deps=','.join(all_deps))))

    add_to_build_file('common/a', 'a')
    add_to_build_file('common/b', 'b')
    add_to_build_file('common/c', 'c')
    add_to_build_file('overlaps', 'one', 'common/a', 'common/b')
    add_to_build_file('overlaps', 'two', 'common/a', 'common/c')
    add_to_build_file('overlaps', 'three', 'common/a', 'overlaps:one')

  def test_roots(self):
    self.assert_console_output(
      'common/a:a',
      targets=[self.target('common/a')],
      extra_targets=[self.target('common/b')]
    )

  def test_nodups(self):
    targets = [self.target('common/a')] * 2
    self.assertEqual(2, len(targets))
    self.assert_console_output(
      'common/a:a',
      targets=targets
    )

  def test_disjoint(self):
    self.assert_console_output(
      'common/a:a',
      'common/b:b',
      'common/c:c',
      targets=[
        self.target('common/a'),
        self.target('common/b'),
        self.target('common/c'),
      ]
    )

  def test_identical(self):
    self.assert_console_output(
      'common/a:a',
      targets=[
        self.target('common/a'),
        self.target('common/a'),
        self.target('common/a'),
      ]
    )

  def test_intersection(self):
    self.assert_console_output(
      'overlaps:one',
      'overlaps:two',
      targets=[
        self.target('overlaps:one'),
        self.target('overlaps:two')
      ]
    )

    self.assert_console_output(
      'overlaps:one',
      'common/c:c',
      targets=[
        self.target('common/a'),
        self.target('common/b'),
        self.target('common/c'),
        self.target('overlaps:one'),
      ]
    )

    self.assert_console_output(
      'overlaps:two',
      'overlaps:three',
      targets=[
        self.target('common/a'),
        self.target('common/b'),
        self.target('common/c'),
        self.target('overlaps:one'),
        self.target('overlaps:two'),
        self.target('overlaps:three'),
      ]
    )
