# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import object

from future.utils import PY2

from pants.option.optionable import Optionable
from pants.option.scope import ScopeInfo


class GoalOptionsRegistrar(Optionable):
  """Subclass this to register recursive options on all tasks in a goal.

  This is useful when you want the possibility of setting the value for all tasks
  at once and/or setting them per-task. E.g., turning all linters on or off, or
  turning individual linters on or off selectively.
  """
  options_scope_category = ScopeInfo.GOAL

  @classmethod
  def registrar_for_scope(cls, goal):
    """Returns a subclass of this registrar suitable for registering on the specified goal.

    Allows reuse of the same registrar for multiple goals, and also allows us to decouple task
    code from knowing which goal(s) the task is to be registered in.
    """
    type_name = '{}_{}'.format(cls.__name__, goal)
    if PY2:
      type_name = type_name.encode('utf-8')
    return type(type_name, (cls, ), {'options_scope': goal})


class GoalOptionsMixin(object):
  """A mixin for tasks that inherit options registered at the goal level."""
  # Subclasses must set this to the appropriate subclass of GoalOptionsRegistrar.
  goal_options_registrar_cls = None
