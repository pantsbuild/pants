# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.goal.goal import Goal
from pants.goal.task_registrar import TaskRegistrar as task
from pants.task.goal_options_mixin import GoalOptionsMixin, GoalOptionsRegistrar
from pants.task.task import Task


class EchoOptionsRegistrar(GoalOptionsRegistrar):
  options_scope = 'echo'

  @classmethod
  def register_options(cls, register):
    register('--enable', type=bool, default=False, recursive=True, help='')


class EchoTaskBase(GoalOptionsMixin, Task):
  goal_options_registrar_cls = EchoOptionsRegistrar
  to_echo = None

  def execute(self):
    with open(os.path.join(self.workdir, 'output'), 'w') as fp:
      fp.write(self.to_echo if self.get_options().enable else b'0')


class EchoOne(EchoTaskBase):
  to_echo = b'1'


class EchoTwo(EchoTaskBase):
  to_echo = b'2'


def register_goals():
  Goal.register('echo', 'test tasks that echo', options_registrar_cls=EchoOptionsRegistrar)
  task(name='one', action=EchoOne).install('echo')
  task(name='two', action=EchoTwo).install('echo')
