# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from optparse import OptionGroup

from pants.goal.error import GoalError
from pants.goal.mkflag import Mkflag


class Goal(object):
  """Factory for objects representing goals.

  Ensures that we have exactly one instance per goal name.
  """
  _goal_by_name = dict()

  def __new__(cls, *args, **kwargs):
    raise TypeError('Do not instantiate {0}. Call by_name() instead.'.format(cls))

  @classmethod
  def by_name(cls, name):
    """Returns the unique object representing the goal of the specified name."""
    if name not in cls._goal_by_name:
      cls._goal_by_name[name] = _Goal(name)
    return cls._goal_by_name[name]

  @classmethod
  def clear(cls):
    """Remove all goals and tasks.

    This method is EXCLUSIVELY for use in tests.
    """
    cls._goal_by_name.clear()

  @staticmethod
  def scope(goal_name, task_name):
    """Returns options scope for specified task in specified goal."""
    return goal_name if goal_name == task_name else '{0}.{1}'.format(goal_name, task_name)

  @staticmethod
  def all():
    """Returns all registered goals, sorted alphabetically by name."""
    return [pair[1] for pair in sorted(Goal._goal_by_name.items())]


class _Goal(object):
  def __init__(self, name):
    """Don't call this directly.

    Create goals only through the Goal.by_name() factory.
    """
    self.name = name
    self.description = None
    self.serialize = False
    self._task_type_by_name = {}  # name -> Task subclass.
    self._ordered_task_names = []  # The task names, in the order imposed by registration.

  def register_options(self, options):
    for task_type in sorted(self.task_types(), key=lambda cls: cls.options_scope):
      task_type.register_options_on_scope(options)

  def install(self, task_registrar, first=False, replace=False, before=None, after=None):
    """Installs the given task in this goal.

    The placement of the task in this goal's execution list defaults to the end but its position
    can be influenced by specifying exactly one of the following arguments:

    first: Places the task 1st in the execution list.
    replace: Removes all existing tasks in this goal and installs this task.
    before: Places the task before the named task in the execution list.
    after: Places the task after the named task in the execution list.
    """
    if [bool(place) for place in [first, replace, before, after]].count(True) > 1:
      raise GoalError('Can only specify one of first, replace, before or after')

    task_name = task_registrar.name
    options_scope = Goal.scope(self.name, task_name)

    # Currently we need to support registering the same task type multiple times in different
    # scopes. However we still want to have each task class know the options scope it was
    # registered in. So we create a synthetic subclass here.
    # TODO(benjy): Revisit this when we revisit the task lifecycle. We probably want to have
    # a task *instance* know its scope, but this means converting option registration from
    # a class method to an instance method, and instantiating the task much sooner in the
    # lifecycle.

    subclass_name = b'{0}_{1}'.format(task_registrar.task_type.__name__,
                                      options_scope.replace('.', '_').replace('-', '_'))
    task_type = type(subclass_name, (task_registrar.task_type,), {'options_scope': options_scope})

    otn = self._ordered_task_names
    if replace:
      for tt in self.task_types():
        tt.options_scope = None
      del otn[:]
      self._task_type_by_name = {}
    if first:
      otn.insert(0, task_name)
    elif before in otn:
      otn.insert(otn.index(before), task_name)
    elif after in otn:
      otn.insert(otn.index(after) + 1, task_name)
    else:
      otn.append(task_name)

    self._task_type_by_name[task_name] = task_type

    if task_registrar.serialize:
      self.serialize = True

    return self

  def with_description(self, description):
    """Add a description to this goal."""
    self.description = description
    return self

  def uninstall_task(self, name):
    """Removes the named task from this goal.

    Allows external plugins to modify the execution plan. Use with caution.

    Note: Does not relax a serialization requirement that originated
    from the uninstalled task's install() call.
    """
    if name in self._task_type_by_name:
      self._task_type_by_name[name].options_scope = None
      del self._task_type_by_name[name]
      self._ordered_task_names = [x for x in self._ordered_task_names if x != name]
    else:
      raise GoalError('Cannot uninstall unknown task: {0}'.format(name))

  def known_scopes(self):
    """Yields all known scopes under this goal (including its own.)"""
    yield self.name
    for task_type in self.task_types():
      for scope in task_type.known_scopes():
        if scope != self.name:
          yield scope

  def ordered_task_names(self):
    """The task names in this goal, in registration order."""
    return self._ordered_task_names

  def task_type_by_name(self, name):
    """The task type registered under the given name."""
    return self._task_type_by_name[name]

  def task_types(self):
    """Returns the task types in this goal, unordered."""
    return self._task_type_by_name.values()

  def has_task_of_type(self, typ):
    """Returns True if this goal has a task of the given type (or a subtype of it)."""
    for task_type in self.task_types():
      if issubclass(task_type, typ):
        return True
    return False

  def __repr__(self):
    return self.name
