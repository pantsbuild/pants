# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from abc import abstractmethod

from twitter.common.lang import AbstractClass

from pants.goal.goal import GoalError
from pants.base.exceptions import TaskError


class Engine(AbstractClass):
  """An engine for running a pants command line."""

  @staticmethod
  def execution_order(phases):
    """Yields all phases needed to attempt the given phases in proper phase execution order."""

    # Its key that we process phase dependencies depth first to maintain initial phase ordering as
    # passed in when phase graphs are dependency disjoint.  A breadth first sort could mix next
    # order executions and violate the implied intent of the passed in phase ordering.

    processed = set()

    def order(_phases):
      for phase in _phases:
        if phase not in processed:
          processed.add(phase)
          for goal in phase.goals():
            for dep in order(goal.dependencies):
              yield dep
          yield phase

    for ordered in order(phases):
      yield ordered

  def execute(self, context, phases):
    """Executes the supplied phases and their dependencies against the given context.

    :param context: The pants run context.
    :param list phases: A list of ``Phase`` objects representing the command line goals explicitly
                        requested.
    :returns int: An exit code of 0 upon success and non-zero otherwise.
    """
    try:
      self.attempt(context, phases)
      return 0
    except (TaskError, GoalError) as e:
      message = '%s' % e
      if message:
        print('\nFAILURE: %s\n' % e)
      else:
        print('\nFAILURE\n')
      return e.exit_code if isinstance(e, TaskError) else 1

  @abstractmethod
  def attempt(self, context, phases):
    """Given the target context and phases specified (command line goals), attempt to achieve all
    goals.

    :param context: The pants run context.
    :param list phases: A list of ``Phase`` objects representing the command line goals explicitly
                        requested.
    """
