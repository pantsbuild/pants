# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class TaskError(Exception):
  """Indicates a task has failed."""

  def __init__(self, *args, **kwargs):
    """
    :param int exit_code: an optional exit code (default=1)
    :param list failed_targets: an optional list of failed targets (default=[])
    """
    self._exit_code = kwargs.pop('exit_code', 1)
    self._failed_targets = kwargs.pop('failed_targets', [])
    super(TaskError, self).__init__(*args, **kwargs)

  @property
  def exit_code(self):
    return self._exit_code

  @property
  def failed_targets(self):
    return self._failed_targets


class TestFailedTaskError(TaskError):
  """Raised when an actual test run failed.

  This is used to distinguish test run failures from infrastructure failures.
  """


class TargetDefinitionException(Exception):
  """Indicates an invalid target definition."""

  def __init__(self, target, msg):
    """
    :param target: the target in question
    :param string msg: a description of the target misconfiguration
    """
    super(Exception, self).__init__('Invalid target {}: {}'.format(target, msg))


class BuildConfigurationError(Exception):
  """Indicates an error in a pants installation's configuration."""


class BackendConfigurationError(BuildConfigurationError):
  """Indicates a plugin backend with a missing or malformed register module."""
