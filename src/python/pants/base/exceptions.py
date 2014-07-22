# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


class TaskError(Exception):
  """Indicates a task has failed."""

  def __init__(self, *args, **kwargs):
    """:param int exit_code: an optional exit code (1, by default)"""
    self._exit_code = kwargs.pop('exit_code', 1)
    super(TaskError, self).__init__(*args, **kwargs)

  @property
  def exit_code(self):
    return self._exit_code


class TargetDefinitionException(Exception):
  """Indicates an invalid target definition."""

  def __init__(self, target, msg):
    """
    :param target: the target in question
    :param string msg: a description of the target misconfiguration
    """
    super(Exception, self).__init__('Invalid target %s: %s' % (target, msg))


class BuildConfigurationError(Exception):
  """Indicates an error in a pants installation's configuration."""


class BackendConfigurationError(BuildConfigurationError):
  """Indicates a plugin backend with a missing or malformed register module."""
