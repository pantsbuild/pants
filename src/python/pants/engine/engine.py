# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from abc import abstractmethod

from twitter.common.lang import AbstractClass

from pants.base.exceptions import TaskError


class Engine(AbstractClass):
  """An engine for running a pants command line."""

  @staticmethod
  def execution_order(goals):
    """Yields all goals needed to attempt the given goals in proper goal execution order."""

    # Its key that we process goal dependencies depth first to maintain initial goal ordering as
    # passed in when goal graphs are dependency disjoint.  A breadth first sort could mix next
    # order executions and violate the implied intent of the passed in goal ordering.

    processed = set()

    def order(_goals):
      for goal in _goals:
        if goal not in processed:
          processed.add(goal)
          for dep in order(goal.dependencies):
            yield dep
          yield goal

    for ordered in order(goals):
      yield ordered

  def execute(self, context, goals):
    """Executes the supplied goals and their dependencies against the given context.

    :param context: The pants run context.
    :param list goals: A list of ``Goal`` objects representing the command line goals explicitly
                       requested.
    :returns int: An exit code of 0 upon success and non-zero otherwise.
    """
    try:
      self.attempt(context, goals)
      return 0
    except TaskError as e:
      message = '%s' % e
      if message:
        print('\nFAILURE: %s\n' % e)
      else:
        print('\nFAILURE\n')
      return e.exit_code if isinstance(e, TaskError) else 1

  @abstractmethod
  def attempt(self, context, goals):
    """Given the target context and command line goals, attempt to achieve all goals.

    :param context: The pants run context.
    :param list goals: A list of ``Goal`` objects representing the command line goals explicitly
                       requested.
    """
