# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import errno
import logging
import subprocess


logger = logging.getLogger(__name__)


class Xargs:
  """A subprocess execution wrapper in the spirit of the xargs command line tool.

  Specifically allows encapsulated commands to be passed very large argument lists by chunking up
  the argument lists into a minimal set and then invoking the encapsulated command against each
  chunk in turn.
  """

  @classmethod
  def subprocess(cls, cmd, **kwargs):
    """Creates an xargs engine that uses subprocess.call to execute the given cmd array with extra
    arg chunks.
    """
    def call(args):
      return subprocess.call(cmd + args, **kwargs)
    return cls(call)

  def __init__(self, cmd, constant_args=None):
    """Creates an xargs engine that calls cmd with argument chunks.

    :param cmd: A function that can execute a command line in the form of a list of strings
      passed as its sole argument.
    :param constant_args: Any positional arguments to be added to each invocation.
    """
    self._cmd = cmd
    self._constant_args = constant_args or []

  def _split_args(self, args):
    half = len(args) // 2
    return args[:half], args[half:]

  def execute(self, args):
    """Executes the configured cmd passing args in one or more rounds xargs style.

    :param list args: Extra arguments to pass to cmd.
    """
    splittable_args = list(args)
    all_args_for_command_function = self._constant_args + [splittable_args]
    logger.debug(f'xargs all_args_for_command_function: {all_args_for_command_function}')
    try:
      return self._cmd(*all_args_for_command_function)
    except OSError as e:
      if errno.E2BIG == e.errno:
        args1, args2 = self._split_args(splittable_args)
        logger.debug(f'xargs split cmd line:\nargs1={args1},\nargs2={args2}!')
        result = self.execute(args1)
        if result != 0:
          return result
        return self.execute(args2)
      else:
        raise e
