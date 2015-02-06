# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.core.tasks.sorttargets import SortTargets
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.build_file_aliases import BuildFileAliases
from pants_test.tasks.test_base import ConsoleTaskTest


class BaseSortTargetsTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return SortTargets


class SortTargetsEmptyTest(BaseSortTargetsTest):
  def test(self):
    self.assert_console_output(targets=[])


class SortTargetsTest(BaseSortTargetsTest):
  @property
  def alias_groups(self):
    return BuildFileAliases.create(targets={'python_library': PythonLibrary})

  def setUp(self):
    super(SortTargetsTest, self).setUp()

    def add_to_build_file(path, name, *deps):
      all_deps = ["'%s'" % dep for dep in list(deps)]
      self.add_to_build_file(path, dedent('''
          python_library(name='%s',
            dependencies=[%s]
          )
          ''' % (name, ','.join(all_deps))))

    add_to_build_file('common/a', 'a')
    add_to_build_file('common/b', 'b', 'common/a')
    add_to_build_file('common/c', 'c', 'common/a', 'common/b')

  def test_sort(self):
    targets = [self.target('common/a'), self.target('common/c'), self.target('common/b')]
    self.assertEqual(['common/a:a', 'common/b:b', 'common/c:c'],
                     list(self.execute_console_task(targets=targets)))

  def test_sort_reverse(self):
    targets = [self.target('common/c'), self.target('common/a'), self.target('common/b')]
    self.assertEqual(['common/c:c', 'common/b:b', 'common/a:a'],
                     list(self.execute_console_task(targets=targets, args=['--test-reverse'])))
