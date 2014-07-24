# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest2

from pants.goal.goal import Goal
from pants.goal.phase import Phase


class EngineTestBase(unittest2.TestCase):

  @classmethod
  def as_phase(cls, phase_name):
    """Returns a ``Phase`` object of the given name"""
    return Phase(phase_name)

  @classmethod
  def as_phases(cls, *phase_names):
    """Converts the given phase names to a list of ``Phase`` objects."""
    return map(cls.as_phase, phase_names)

  @classmethod
  def install_goal(cls, name, action=None, dependencies=None, phase=None):
    """Creates and installs a goal with the given name.

    :param string name: The goal name.
    :param action: The goal's action.
    :param list dependencies: The list of phase names the goal depends on, if any.
    :param string phase: The name of the phase to install the goal in if different from the goal
      name.
    :returns The installed ``Goal`` object.
    """
    goal = Goal(name, action=action or (lambda: None), dependencies=dependencies or [])
    goal.install(phase if phase is not None else None)
    return goal

  def setUp(self):
    super(EngineTestBase, self).setUp()

    # TODO(John Sirois): Now that the BuildFileParser controls goal registration by iterating
    # over plugin callbacks a PhaseRegistry can be constructed by it and handed to all these
    # callbacks in place of having a global Phase registry.  Remove the Phase static cling.
    Phase.clear()

  def tearDown(self):
    Phase.clear()

    super(EngineTestBase, self).tearDown()
