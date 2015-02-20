# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod

from pants.base.exceptions import TaskError
from pants.util.meta import AbstractClass


class Engine(AbstractClass):
  """An engine for running a pants command line."""

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
      message = str(e)
      if message:
        print('\nFAILURE: {0}\n'.format(message))
      else:
        print('\nFAILURE\n')
      return e.exit_code

  @abstractmethod
  def attempt(self, context, goals):
    """Given the target context and command line goals, attempt to achieve all goals.

    :param context: The pants run context.
    :param list goals: A list of ``Goal`` objects representing the command line goals explicitly
                       requested.
    """
