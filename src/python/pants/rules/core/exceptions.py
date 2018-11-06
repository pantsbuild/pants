# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals


class GracefulTerminationException(Exception):
  """Indicates that a console_rule should eagerly terminate the run.

  No error trace will be printed if this is raised; the runner will simply exit with the passed
  exit code.

  Nothing except a console_rule should ever raise this.
  """

  def __init__(self, message='', exit_code=1):
    """
    :param int exit_code: an optional exit code (default=1)
    """
    super(GracefulTerminationException, self).__init__(message)

    if exit_code == 0:
      raise ValueError("Cannot create GracefulTerminationException with exit code of 0")

    self._exit_code = exit_code

  @property
  def exit_code(self):
    return self._exit_code
