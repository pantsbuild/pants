# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict

from pants.goal.error import GoalError


class SingletonPhases(type):
  phases = dict()
  renames = dict()

  def rename(cls, phase, name):
    """
      Renames the given phase and ensures all future requests for the old name are mapped to the
      given phase instance.
    """
    cls.phases.pop(phase.name)
    cls.renames[phase.name] = name
    phase.name = name
    cls.phases[name] = phase

  def __call__(cls, name):
    name = cls.renames.get(name, name)
    if name not in cls.phases:
      cls.phases[name] = super(SingletonPhases, cls).__call__(name)
    return cls.phases[name]

# Python 2.x + 3.x wankery
PhaseBase = SingletonPhases(str('PhaseBase'), (object,), {})


class Phase(PhaseBase):
  _goals_by_phase = defaultdict(list)
  _phase_by_goal = dict()

  @classmethod
  def clear(cls):
    """Remove all phases and goals.

    This method is EXCLUSIVELY for use in tests.
    """
    cls._goals_by_phase.clear()
    cls._phase_by_goal.clear()

  @staticmethod
  def of(goal):
    return Phase._phase_by_goal[goal]

  @staticmethod
  def goals_of_type(goal_class):
    """Returns all installed goals of the specified type."""
    return [goal for goal in Phase._phase_by_goal.keys() if isinstance(goal, goal_class)]

  @staticmethod
  def setup_parser(parser, args, phases):
    """Set up an OptionParser with options info for a phase and its deps.
    This readies the parser to handle options for this phase and its deps.
    It does not set up everything you might want for displaying help.
    For that, you want setup_parser_for_help.
    """
    def do_setup_parser(phase, setup):
      for goal in phase.goals():
        if goal not in setup:
          setup.add(goal)
          for dep in goal.dependencies:
            do_setup_parser(dep, setup)
          goal.setup_parser(phase, parser, args)

    setup = set()
    for phase in phases:
      do_setup_parser(phase, setup)

  @staticmethod
  def all():
    """Returns all registered goals as a sorted sequence of phase, goals tuples."""
    return sorted(Phase._goals_by_phase.items(), key=lambda pair: pair[0].name)

  def __init__(self, name):
    self.name = name
    self.description = None

  def with_description(self, description):
    self.description = description
    return self

  def install(self, goal, first=False, replace=False, before=None, after=None):
    """
      Installs the given goal in this phase.  The placement of the goal in this phases' execution
      list defaults to the end but its position can be influence by specifying exactly one of the
      following arguments:

      first: Places the goal 1st in the execution list
      replace: Removes all existing goals in this phase and installs this goal
      before: Places the goal before the named goal in the execution list
      after: Places the goal after the named goal in the execution list
    """

    if [bool(place) for place in [first, replace, before, after]].count(True) > 1:
      raise GoalError('Can only specify one of first, replace, before or after')

    Phase._phase_by_goal[goal] = self

    g = self.goals()
    if replace:
      del g[:]
    g_names = map(lambda goal: goal.name, g)
    if first:
      g.insert(0, goal)
    elif before in g_names:
      g.insert(g_names.index(before), goal)
    elif after in g_names:
      g.insert(g_names.index(after) + 1, goal)
    else:
      g.append(goal)
    return self

  def rename(self, name):
    """Renames this goal."""
    PhaseBase.rename(self, name)
    return self

  def copy_to(self, name):
    """Copies this phase to the new named phase carrying along goal dependencies and description."""
    copy = Phase(name)
    copy.goals().extend(self.goals())
    copy.description = self.description
    return copy

  def remove(self, name):
    """Removes the named goal from this phase's list of goals to attempt."""
    goals = self.goals()
    for goal in goals:
      if goal.name == name:
        goals.remove(goal)
        return self
    raise GoalError('Goal %s does not exist in this phase, members are: %s' % (name, goals))

  class UnsatisfiedDependencyError(GoalError):
    """Raised when an operation cannot be completed due to an unsatisfied goal dependency."""

  def uninstall(self):
    """
      Removes the named phase and all its attached goals.  Raises Phase.UnsatisfiedDependencyError
      if the removal cannot be completed due to a dependency.
    """
    for phase, goals in Phase._goals_by_phase.items():
      for goal in goals:
        for dependee_phase in goal.dependencies:
          if self is dependee_phase:
            raise Phase.UnsatisfiedDependencyError(
              '%s is depended on by %s:%s' % (self.name, phase.name, goal.name))
    del Phase._goals_by_phase[self]

  def goals(self):
    return Phase._goals_by_phase[self]

  def serialize(self):
    return any([x.serialize for x in self.goals()])

  def __repr__(self):
    return self.name
