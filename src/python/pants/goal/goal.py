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
  def option_group_title(goal, task_name):
    """Returns name to use for CLI flag OptionGroup."""
    goal_leader = len(goal.ordered_task_names()) == 1 or task_name == goal.name
    namespace = [task_name] if goal_leader else [goal.name, task_name]
    return ':'.join(namespace)

  @staticmethod
  def setup_parser(parser, args, goals):
    """Set up an OptionParser with options info for a goal and its deps.
    This readies the parser to handle options for this goal and its deps.
    It does not set up everything you might want for displaying help.
    For that, you want setup_parser_for_help.
    """
    visited = set()

    def do_setup_parser(goal):
      if goal not in visited:
        visited.add(goal)
        for dep in goal.dependencies:
          do_setup_parser(dep)
        for task_name in goal.ordered_task_names():
          task_type = goal.task_type_by_name(task_name)
          goal_leader = len(goal.ordered_task_names()) == 1 or task_name == goal.name
          namespace = [task_name] if goal_leader else [goal.name, task_name]
          mkflag = Mkflag(*namespace)
          option_group = OptionGroup(parser, title=Goal.option_group_title(goal, task_name))
          task_type.setup_parser(option_group, args, mkflag)
          if option_group.option_list:
            parser.add_option_group(option_group)

    for goal in goals:
      do_setup_parser(goal)

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
    self.dependencies = set()  # The Goals this Goal depends on.
    self.serialize = False
    self._task_type_by_name = {}  # name -> Task subclass.
    self._ordered_task_names = []  # The task names, in the order imposed by registration.

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
    self._task_type_by_name[task_name] = task_registrar.task_type

    otn = self._ordered_task_names
    if replace:
      del otn[:]
    if first:
      otn.insert(0, task_name)
    elif before in otn:
      otn.insert(otn.index(before), task_name)
    elif after in otn:
      otn.insert(otn.index(after) + 1, task_name)
    else:
      otn.append(task_name)

    self.dependencies.update(task_registrar.dependencies)

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

    Note: Does not remove goal dependencies or relax a serialization requirement that originated
    from the uninstalled task's install() call.
    TODO(benjy): Should it? We're moving away from explicit goal deps towards a
                 product consumption-production model anyway.
    """
    if name in self._task_type_by_name:
      del self._task_type_by_name[name]
      self._ordered_task_names = [x for x in self._ordered_task_names if x != name]
    else:
      raise GoalError('Cannot uninstall unknown task: {0}'.format(name))


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
