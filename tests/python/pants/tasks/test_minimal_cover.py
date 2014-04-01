# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

from pants.tasks.minimal_cover import MinimalCover
from pants.tasks.test_base import ConsoleTaskTest


class BaseMinimalCovertTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return MinimalCover


class MinimalCoverEmptyTest(BaseMinimalCovertTest):
  def test(self):
    self.assert_console_output(targets=[])


class MinimalCoverTest(BaseMinimalCovertTest):

  @classmethod
  def setUpClass(cls):
    super(MinimalCoverTest, cls).setUpClass()

    def create_target(path, name, *deps):
      all_deps = ["pants('%s')" % dep for dep in list(deps)]
      cls.create_target(path, dedent('''
          python_library(name='%s',
            dependencies=[%s]
          )
          ''' % (name, ','.join(all_deps))))

    create_target('common/a', 'a')
    create_target('common/b', 'b')
    create_target('common/c', 'c')
    create_target('overlaps', 'one', 'common/a', 'common/b')
    create_target('overlaps', 'two', 'common/a', 'common/c')
    create_target('overlaps', 'three', 'common/a', 'overlaps:one')

  def test_roots(self):
    self.assert_console_output(
      'common/a/BUILD:a',
      targets=[self.target('common/a')],
      extra_targets=[self.target('common/b')]
    )

  def test_nodups(self):
    targets = [self.target('common/a')] * 2
    self.assertEqual(2, len(targets))
    self.assert_console_output(
      'common/a/BUILD:a',
      targets=targets
    )

  def test_disjoint(self):
    self.assert_console_output(
      'common/a/BUILD:a',
      'common/b/BUILD:b',
      'common/c/BUILD:c',
      targets=[
        self.target('common/a'),
        self.target('common/b'),
        self.target('common/c'),
      ]
    )

  def test_identical(self):
    self.assert_console_output(
      'common/a/BUILD:a',
      targets=[
        self.target('common/a'),
        self.target('common/a'),
        self.target('common/a'),
      ]
    )

  def test_intersection(self):
    self.assert_console_output(
      'overlaps/BUILD:one',
      'overlaps/BUILD:two',
      targets=[
        self.target('overlaps:one'),
        self.target('overlaps:two')
      ]
    )

    self.assert_console_output(
      'overlaps/BUILD:one',
      'common/c/BUILD:c',
      targets=[
        self.target('common/a'),
        self.target('common/b'),
        self.target('common/c'),
        self.target('overlaps:one'),
      ]
    )

    self.assert_console_output(
      'overlaps/BUILD:two',
      'overlaps/BUILD:three',
      targets=[
        self.target('common/a'),
        self.target('common/b'),
        self.target('common/c'),
        self.target('overlaps:one'),
        self.target('overlaps:two'),
        self.target('overlaps:three'),
      ]
    )
