# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod

from pants.base.exceptions import TestFailedTaskError
from pants.util.timeout import Timeout, TimeoutReached


class TestTaskMixin(object):
  """A mixin to combine with test runner tasks.

  The intent is to migrate logic over time out of JUnitRun and PytestRun, so the functionality
  expressed can support both languages, and any additional languages that are added to pants.
  """

  @classmethod
  def register_options(cls, register):
    super(TestTaskMixin, cls).register_options(register)
    register('--skip', action='store_true', help='Skip running tests.')
    register('--timeouts', action='store_true', default=True,
             help="Enable test target timeouts. If timeouts are enabled then tests with a target= parameter "
             "set on their target will time out after the given number of seconds if not completed. "
             "If no timeout is set, then either the default timeout is used or no timeout is configured. "
             "In the current implementation, all the timeouts for the test targets to be run are summed and "
             "all tests are run with the total timeout covering the entire run of tests. This should "
             "change in the future to provide more granularity.")
    register('--timeout-default', action='store', default=0, type=int,
             help='The default timeout (in seconds) for a test if timeout is not set on the target.')

  def execute(self):
    """Run the task."""

    if not self.get_options().skip:
      test_targets = self._get_test_targets()
      all_targets = self._get_targets()
      for target in test_targets:
        self._validate_target(target)

      timeout = self._timeout_for_targets(test_targets)
      try:
        with Timeout(timeout):
          self._execute(all_targets)
      except TimeoutReached:
        raise TestFailedTaskError(failed_targets=test_targets)

  def _timeout_for_target(self, target):
    return getattr(target, 'timeout', None)

  def _timeout_for_targets(self, targets):
    """Calculate the total timeout based on the timeout configuration for all the targets.

    Because the timeout wraps all the test targets rather than individual tests, we have to somehow
    aggregate all the target specific timeouts into one value that will cover all the tests. If some targets
    have no timeout configured (or set to 0), their timeout will be set to the default timeout.
    If there is no default timeout, or if it is set to zero, there will be no timeout, if any of the test targets
    have a timeout set to 0 or no timeout configured.

    :param targets: list of test targets
    :return: timeout to cover all the targets, in seconds
    """

    if not self.get_options().timeouts:
      return None

    timeout_default = self.get_options().timeout_default

    # Gather up all the timeouts.
    timeouts = [self._timeout_for_target(target) for target in targets]

    # If any target's timeout is None or 0, then set it to the default timeout
    timeouts_w_default = [timeout or timeout_default for timeout in timeouts]

    # Even after we've done that, there may be a 0 or None in the timeout list if the
    # default timeout is set to 0 or None. So if that's the case, then the timeout is
    # disabled
    if 0 in timeouts_w_default or None in timeouts_w_default:
      return None
    else:
      # Sum the timeouts for all the targets, using the default timeout where one is not set
      return sum(timeouts_w_default)

  def _get_targets(self):
    """This is separated out so it can be overridden for testing purposes.

    :return: list of targets
    """
    return self.context.targets()

  def _get_test_targets(self):
    """Returns the targets that are relevant test targets."""

    test_targets = list(filter(self._test_target_filter(), self._get_targets()))
    return test_targets

  @abstractmethod
  def _test_target_filter(self):
    """A filter to run on targets to see if they are relevant to this test task.

    :return: function from target->boolean
    """

  @abstractmethod
  def _validate_target(self, target):
    """Ensures that this target is valid. Raises TargetDefinitionException if the target is invalid.

    We don't need the type check here because _get_targets() combines with _test_target_type to
    filter the list of targets to only the targets relevant for this test task.
im
    :param target: the target to validate
    :raises: TargetDefinitionException
    """

  @abstractmethod
  def _execute(self, all_targets):
    """Actually goes ahead and runs the tests for the targets.

    :param targets: list of the targets whose tests are to be run
    """
