# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod

from pants.base.exceptions import TaskError


class Engine(ABC):
    """An engine for running a pants command line."""

    def execute(self, context, goals) -> int:
        """Executes the supplied goals and their dependencies against the given context.

        :param context: The pants run context.
        :param list goals: A list of ``Goal`` objects representing the command line goals explicitly
                           requested.
        :returns an exit code of 0 upon success and non-zero otherwise.
        """
        try:
            self.attempt(context, goals)
            return 0
        except TaskError as e:
            message = str(e)
            if message:
                print("\nFAILURE: {0}\n".format(message))
            else:
                print("\nFAILURE\n")
            return e.exit_code

    @abstractmethod
    def attempt(self, context, goals):
        """Given the target context and command line goals, attempt to achieve all goals.

        :param context: The pants run context.
        :param list goals: A list of ``Goal`` objects representing the command line goals explicitly
                           requested.
        """
