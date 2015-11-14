# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.core.tasks.sorttargets import SortTargets
from pants.backend.python.targets.python_library import PythonLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class BaseSortTargetsTest(ConsoleTaskTestBase):

  @classmethod
  def task_type(cls):
    return SortTargets


class SortTargetsEmptyTest(BaseSortTargetsTest):

  def test(self):
    self.assert_console_output(targets=[])


class SortTargetsTest(BaseSortTargetsTest):

  @property
  def alias_groups(self):
    return BuildFileAliases(targets={'python_library': PythonLibrary})

  def setUp(self):
    super(SortTargetsTest, self).setUp()

    def add_to_build_file(path, name, *deps):
      all_deps = ["'{0}'".format(dep) for dep in list(deps)]
      self.add_to_build_file(path, dedent("""
          python_library(name='{name}',
            dependencies=[{all_deps}]
          )
          """.format(name=name, all_deps=','.join(all_deps))))

    add_to_build_file('common/a', 'a')
    add_to_build_file('common/b', 'b', 'common/a')
    add_to_build_file('common/c', 'c', 'common/a', 'common/b')

  def test_sort(self):
    targets = [self.target('common/a'), self.target('common/c'), self.target('common/b')]
    self.assertEqual(['common/a', 'common/b', 'common/c'],
                     list(self.execute_console_task(targets=targets)))

  def test_sort_reverse(self):
    targets = [self.target('common/c'), self.target('common/a'), self.target('common/b')]
    self.assertEqual(['common/c', 'common/b', 'common/a'],
                     list(self.execute_console_task(targets=targets, options={'reverse': True})))
