# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

from pants.tasks.sorttargets import SortTargets
from pants.tasks.test_base import ConsoleTaskTest


class BaseSortTargetsTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return SortTargets


class SortTargetsEmptyTest(BaseSortTargetsTest):
  def test(self):
    self.assert_console_output(targets=[])


class SortTargetsTest(BaseSortTargetsTest):

  @classmethod
  def setUpClass(cls):
    super(SortTargetsTest, cls).setUpClass()

    def create_target(path, name, *deps):
      all_deps = ["pants('%s')" % dep for dep in list(deps)]
      cls.create_target(path, dedent('''
          python_library(name='%s',
            dependencies=[%s]
          )
          ''' % (name, ','.join(all_deps))))

    create_target('common/a', 'a')
    create_target('common/b', 'b', 'common/a')
    create_target('common/c', 'c', 'common/a', 'common/b')

  def test_sort(self):
    targets = [self.target('common/a'), self.target('common/c'), self.target('common/b')]
    self.assertEqual(['common/a/BUILD:a', 'common/b/BUILD:b', 'common/c/BUILD:c'],
                     list(self.execute_console_task(targets=targets)))

  def test_sort_reverse(self):
    targets = [self.target('common/c'), self.target('common/a'), self.target('common/b')]
    self.assertEqual(['common/c/BUILD:c', 'common/b/BUILD:b', 'common/a/BUILD:a'],
                     list(self.execute_console_task(targets=targets, args=['--test-reverse'])))
