# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE


class GracefulTerminationException(Exception):
  """Indicates that a console_rule should eagerly terminate the run.

  No error trace will be printed if this is raised; the runner will simply exit with the passed
  exit code.

  Nothing except a console_rule should ever raise this.
  """

  def __init__(self, message='', exit_code=PANTS_FAILED_EXIT_CODE):
    """
    :param int exit_code: an optional exit code (defaults to PANTS_FAILED_EXIT_CODE)
    """
    super(GracefulTerminationException, self).__init__(message)

    if exit_code == PANTS_SUCCEEDED_EXIT_CODE:
      raise ValueError(
        "Cannot create GracefulTerminationException with a successful exit code of {}"
        .format(PANTS_SUCCEEDED_EXIT_CODE))

    self._exit_code = exit_code

  @property
  def exit_code(self):
    return self._exit_code
