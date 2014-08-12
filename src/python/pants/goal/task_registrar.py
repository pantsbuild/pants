# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import functools
import inspect

from pants.goal.error import GoalError
from pants.goal.phase import Phase
from pants.backend.core.tasks.task import Task


class TaskRegistrar(object):
  def __init__(self, name, action, dependencies=None, serialize=True):
    """
    :param name: the name of the goal.
    :param action: the goal action object to invoke this goal.
    :param dependencies: the names of other goals which must be achieved before invoking this goal.
    :param serialize: a flag indicating whether or not the action to achieve this goal requires
      the global lock. If true, the action will block until it can acquire the lock.
    """
    self.serialize = serialize
    self.name = name
    self.dependencies = [Phase.by_name(d) for d in dependencies] if dependencies else []

    if isinstance(type(action), type) and issubclass(action, Task):
      self._task = action
    else:
      args, varargs, keywords, defaults = inspect.getargspec(action)
      if varargs or keywords or defaults:
        raise GoalError('Invalid action supplied, cannot accept varargs, keywords or defaults')
      if len(args) > 1:
        raise GoalError('Invalid action supplied, must accept either no args or else a single '
                        'Context object')

      class FuncTask(Task):
        def __init__(self, *args, **kwargs):
          super(FuncTask, self).__init__(*args, **kwargs)

          if not args:
            self.action = action
          elif len(args) == 1:
            self.action = functools.partial(action, self.context)
          else:
            raise AssertionError('Unexpected fallthrough')

        def execute(self):
          self.action()

      self._task = FuncTask

  def __repr__(self):
    return "TaskRegistrar(%s; %s)" % (self.name, ','.join(map(str, self.dependencies)))

  @property
  def task_type(self):
    return self._task

  def install(self, phase=None, first=False, replace=False, before=None, after=None):
    """Install the task in the specified phase (or a new phase with the same name as the task).

    The placement of the goal in the execution list of the phase defaults to the end but can be
    influence by specifying exactly one of the following arguments:

    :param first: Places this goal 1st in the phase's execution list
    :param replace: Replaces any existing goals in the phase with this goal
    :param before: Places this goal before the named goal in the phase's execution list
    :param after: Places this goal after the named goal in the phase's execution list
    """
    phase = Phase.by_name(phase or self.name)
    phase.install(self, first, replace, before, after)
    return phase