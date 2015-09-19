# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys
import traceback
from textwrap import dedent

from pants.goal.goal import Goal


class TaskRegistrar(object):
  def __init__(self, name, action, dependencies=None, serialize=True):
    """
    :param name: the name of the task.
    :param action: the Task action object to invoke this task.
    :param dependencies: DEPRECATED
      the names of other goals which must be achieved before invoking this task's goal.
    :param serialize: a flag indicating whether or not the action to achieve this goal requires
      the global lock. If true, the action will block until it can acquire the lock.
    """
    self.serialize = serialize
    self.name = name
    self._task = action

    if dependencies:
      # TODO(John Sirois): kill this warning and the kwarg after a deprecation cycle.
      print(dedent('''
          WARNING: Registered dependencies are now ignored and only `Task.product_types`
          and product requirements as expressed in `Task.prepare` are used to
          infer Task dependencies.

          Please fix this registration:
            {reg}
            {location}
          ''').format(reg=self,
                      location=traceback.format_list([traceback.extract_stack()[-2]])[0]),
            file=sys.stderr)

  def __repr__(self):
    return 'TaskRegistrar({name}, {action} serialize={serialize})'.format(name=self.name,
                                                                          action=self._task,
                                                                          serialize=self.serialize)

  @property
  def task_type(self):
    return self._task

  def install(self, goal=None, first=False, replace=False, before=None, after=None):
    """Install the task in the specified goal (or a new goal with the same name as the task).

    The placement of the task in the execution list of the goal defaults to the end but can be
    influence by specifying exactly one of the following arguments:

    :param first: Places this task 1st in the goal's execution list.
    :param replace: Replaces any existing tasks in the goal with this goal.
    :param before: Places this task before the named task in the goal's execution list.
    :param after: Places this task after the named task in the goal's execution list.
    :returns: The goal with task installed.
    """
    goal = Goal.by_name(goal or self.name)
    goal.install(self, first, replace, before, after)
    return goal
