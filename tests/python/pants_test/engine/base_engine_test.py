# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.goal.goal import Goal
from pants.goal.task_registrar import TaskRegistrar
from pants_test.test_base import TestBase


class EngineTestBase(TestBase):
  """
  :API: public
  """

  @classmethod
  def as_goal(cls, goal_name):
    """Returns a ``Goal`` object of the given name

    :API: public
    """
    return Goal.by_name(goal_name)

  @classmethod
  def as_goals(cls, *goal_names):
    """Converts the given goal names to a list of ``Goal`` objects.

    :API: public
    """
    return [cls.as_goal(goal_name) for goal_name in goal_names]

  @classmethod
  def install_task(cls, name, action=None, dependencies=None, goal=None):
    """Creates and installs a task with the given name.

    :API: public

    :param string name: The task name.
    :param action: The task's action.
    :param list dependencies: The list of goal names the task depends on, if any.
    :param string goal: The name of the goal to install the task in, if different from the task
                        name.
    :returns The ``Goal`` object with task installed.
    """
    return TaskRegistrar(name,
                         action=action or (lambda: None),
                         dependencies=dependencies or []).install(goal if goal is not None else None)

  def setUp(self):
    """
    :API: public
    """
    super(EngineTestBase, self).setUp()

    # TODO(John Sirois): Now that the BuildFileParser controls goal registration by iterating
    # over plugin callbacks a GoalRegistry can be constructed by it and handed to all these
    # callbacks in place of having a global Goal registry.  Remove the Goal static cling.
    Goal.clear()

  def tearDown(self):
    """
    :API: public
    """
    Goal.clear()

    super(EngineTestBase, self).tearDown()
