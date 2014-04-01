# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.goal import Goal, Phase


class EngineTestBase(unittest.TestCase):

  @classmethod
  def _namespace(cls, identifier):
    return '__%s.%s__%s__' % (cls.__module__, cls.__name__, identifier)

  @classmethod
  def as_phase(cls, phase_name):
    """Returns a ``Phase`` object of the given name"""
    return Phase(cls._namespace(phase_name))

  @classmethod
  def as_phases(cls, *phase_names):
    """Converts the given phase names to a list of ``Phase`` objects."""
    return map(cls.as_phase, phase_names)

  @classmethod
  def installed_goal(cls, name, action=None, group=None, dependencies=None, phase=None):
    """Creates and installs a goal with the given name.

    :param string name: The goal name.
    :param action: The goal's action.
    :param group: The goal's group if it belongs to one.
    :param list dependencies: The list of phase names the goal depends on, if any.
    :param string phase: The name of the phase to install the goal in if different from the goal
      name.
    :returns The installed ``Goal`` object.
    """
    goal = Goal(cls._namespace(name),
                action=action or (lambda: None),
                group=group,
                dependencies=map(cls._namespace, dependencies or []))
    goal.install(cls._namespace(phase) if phase is not None else None)
    return goal
