# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from optparse import OptionGroup

from pants.goal.error import GoalError
from pants.goal.mkflag import Mkflag


class Phase(object):
  """Factory for objects representing phases.

  Ensures that we have exactly one instance per phase name.
  """
  _phase_by_name = dict()

  @classmethod
  def __new__(cls):
    raise TypeError('Do not instantiate {0}. Call by_name() instead.'.format(cls))

  @classmethod
  def by_name(cls, name):
    """Returns the unique object representing the phase of the specified name."""
    if name not in cls._phase_by_name:
      cls._phase_by_name[name] = _Phase(name)
    return cls._phase_by_name[name]

  @classmethod
  def clear(cls):
    """Remove all phases and tasks.

    This method is EXCLUSIVELY for use in tests.
    """
    cls._phase_by_name.clear()

  @staticmethod
  def setup_parser(parser, args, phases):
    """Set up an OptionParser with options info for a phase and its deps.

    This readies the parser to handle options for this phase and its deps.
    It does not set up everything you might want for displaying help.
    For that, you want setup_parser_for_help.
    """
    visited = set()

    def do_setup_parser(phase):
      if phase not in visited:
        visited.add(phase)
        for dep in phase.dependencies:
          do_setup_parser(dep)
        for task_name in phase.ordered_task_names():
          task_type = phase.task_type_by_name(task_name)
          phase_leader = len(phase.ordered_task_names()) == 1 or task_name == phase.name
          namespace = [task_name] if phase_leader else [phase.name, task_name]
          mkflag = Mkflag(*namespace)
          option_group = OptionGroup(parser, title=':'.join(namespace))
          task_type.setup_parser(option_group, args, mkflag)

    for phase in phases:
      do_setup_parser(phase)

  @staticmethod
  def all():
    """Returns all registered phases, sorted alphabetically by name."""
    return [pair[1] for pair in sorted(Phase._phase_by_name.items())]


class _Phase(object):
  def __init__(self, name):
    """Don't call this directly.

    Create phases only through the Phase.by_name() factory.
    """
    self.name = name
    self.description = None
    self.dependencies = set()  # The Phases this Phase depends on.
    self.serialize = False
    self._task_type_by_name = {}  # name -> Task subclass.
    self._ordered_task_names = []  # The task names, in the order imposed by registration.

  def install(self, task_registrar, first=False, replace=False, before=None, after=None):
    """Installs the given task in this phase.

    The placement of the task in this phases' execution list defaults to the end but its position
    can be influenced by specifying exactly one of the following arguments:

    first: Places the task 1st in the execution list
    replace: Removes all existing tasks in this phase and installs this goal
    before: Places the task before the named task in the execution list
    after: Places the task after the named task in the execution list
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
    """Add a description to this phase."""
    self.description = description
    return self

  def ordered_task_names(self):
    """The task names in this phase, in registration order."""
    return self._ordered_task_names

  def task_type_by_name(self, name):
    """The task type registered under the given name."""
    return self._task_type_by_name[name]

  def task_types(self):
    """Returns the task types in this phase, unordered."""
    return self._task_type_by_name.values()

  def has_task_of_type(self, typ):
    """Returns True if this phase has a task of the given type (or a subtype of it)."""
    for task_type in self.task_types():
      if issubclass(task_type, typ):
        return True
    return False

  def __repr__(self):
    return self.name
