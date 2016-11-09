# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.help.scope_info_iterator import ScopeInfoIterator
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.global_options import GlobalOptionsRegistrar
from pants.option.scope import ScopeInfo
from pants.subsystem.subsystem import Subsystem
from pants.subsystem.subsystem_client_mixin import SubsystemDependency
from pants.task.task import Task


class ScopeInfoIteratorTest(unittest.TestCase):
  def test_iteration(self):
    self.maxDiff = None

    class Subsys1(Subsystem):
      options_scope = 'subsys1'

    class Subsys2(Subsystem):
      options_scope = 'subsys2'

      @classmethod
      def subsystem_dependencies(cls):
        return (SubsystemDependency(Subsys1, 'subsys2'),)

    class Goal1Task2(Task):
      options_scope = 'goal1.task12'

      @classmethod
      def subsystem_dependencies(cls):
        return (SubsystemDependency(Subsys1, 'goal1.task12'),)

    infos = [
      ScopeInfo(GLOBAL_SCOPE, ScopeInfo.GLOBAL, GlobalOptionsRegistrar),
      ScopeInfo('subsys2', ScopeInfo.SUBSYSTEM, Subsys2),
      ScopeInfo('subsys1.subsys2', ScopeInfo.SUBSYSTEM, Subsys1),
      ScopeInfo('goal1', ScopeInfo.INTERMEDIATE),
      ScopeInfo('goal1.task11', ScopeInfo.TASK),
      ScopeInfo('goal1.task12', ScopeInfo.TASK, Goal1Task2),
      ScopeInfo('subsys1.goal1.task12', ScopeInfo.SUBSYSTEM, Subsys1),
      ScopeInfo('goal2', ScopeInfo.INTERMEDIATE),
      ScopeInfo('goal2.task21', ScopeInfo.TASK),
      ScopeInfo('goal2.task22', ScopeInfo.TASK),
      ScopeInfo('goal3', ScopeInfo.INTERMEDIATE),
      ScopeInfo('goal3.task31', ScopeInfo.TASK),
      ScopeInfo('goal3.task32', ScopeInfo.TASK),
    ]

    scope_to_infos = dict((x.scope, x) for x in infos)

    it = ScopeInfoIterator(scope_to_infos)
    actual = list(it.iterate([GLOBAL_SCOPE, 'goal1', 'goal2.task21', 'goal3']))

    expected_scopes = [
      GLOBAL_SCOPE,
      'subsys2',
      'subsys1.subsys2',
      'goal1', 'goal1.task11', 'goal1.task12', 'subsys1.goal1.task12',
      'goal2.task21',
      'goal3', 'goal3.task31', 'goal3.task32',
    ]

    expected_scope_infos = [scope_to_infos[x] for x in expected_scopes]

    self.assertEquals(expected_scope_infos, actual)
