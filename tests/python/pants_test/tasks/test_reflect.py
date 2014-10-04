# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import closing
from StringIO import StringIO

from pants.backend.core.tasks import builddictionary
from pants.backend.core.tasks import reflect
from pants.backend.core.register import build_file_aliases as register_core
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.python.register import build_file_aliases as register_python
from pants.goal.goal import Goal
from pants.goal.task_registrar import TaskRegistrar
from pants_test.tasks.test_base import BaseTest, TaskTest, prepare_task


class BuildsymsSanityTests(BaseTest):
  def setUp(self):
    super(BuildsymsSanityTests, self).setUp()
    self._syms = reflect.assemble_buildsyms(build_file_parser=self.build_file_parser)

  def test_exclude_unuseful(self):
    # These symbols snuck into old dictionaries, make sure they don't again:
    for unexpected in ['__builtins__', 'Target']:
      self.assertTrue(unexpected not in self._syms.keys(), 'Found %s' % unexpected)


class GoalDataTest(BaseTest):
  def test_gen_tasks_goals_reference_data(self):
    # can we run our reflection-y goal code without crashing? would be nice
    Goal.by_name('jack').install(TaskRegistrar('jill', lambda: 42))
    gref_data = reflect.gen_tasks_goals_reference_data()
    self.assertTrue(len(gref_data) > 0, 'Tried to generate data for goals reference, got emptiness')
