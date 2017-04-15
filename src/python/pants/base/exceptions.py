# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import warnings


class TaskError(Exception):
  """Indicates a task has failed.

  :API: public
  """

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


class ErrorWhileTesting(TaskError):
  """Raised when an actual test run failed.

  This is used to distinguish test run failures from infrastructure failures.

  :API: public
  """


# Renamed this to ErrorWhileTesting, because pytest will see the `Test` prefix and attempt
# to do test discovery on this class, but then issue this warning:
# "cannot collect test class 'TestFailedTaskError' because it has a __init__ constructor".
class TestFailedTaskError(ErrorWhileTesting):
  def __init__(self, *args, **kwargs):
    # Note that we can't use our regular deprecation mechanism because we want this module
    # to remain dependency-free.
    # Note also that this warning will only trigger if some code actually instantiates
    # an instance of this exception.  This is the best we can do, since there's no
    # way of detecting "this class was imported in some other module".
    # Fortunately, it's pretty unlikely that anyone is actually using this exception...
    msg = ('DEPRECATED: TestFailedTaskError will be removed in version 1.5.0.dev0.\n'
           'Use ErrorWhileTesting instead.')
    warnings.warn(msg)
    super(TestFailedTaskError, self).__init__(*args, **kwargs)


class TargetDefinitionException(Exception):
  """Indicates an invalid target definition.

  :API: public
  """

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
