# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod
from textwrap import dedent

from pants.base.deprecated import deprecated_conditional
from pants.base.exceptions import TestFailedTaskError
from pants.util.timeout import Timeout, TimeoutReached


class TestRunnerTaskMixin(object):
  """A mixin to combine with test runner tasks.

  The intent is to migrate logic over time out of JUnitRun and PytestRun, so the functionality
  expressed can support both languages, and any additional languages that are added to pants.
  """

  @classmethod
  def register_options(cls, register):
    super(TestRunnerTaskMixin, cls).register_options(register)
    register('--skip', action='store_true', help='Skip running tests.')
    register('--timeouts', action='store_true', default=True,
             help='Enable test target timeouts. If timeouts are enabled then tests with a timeout= parameter '
             'set on their target will time out after the given number of seconds if not completed. '
             'If no timeout is set, then either the default timeout is used or no timeout is configured. '
             'In the current implementation, all the timeouts for the test targets to be run are summed and '
             'all tests are run with the total timeout covering the entire run of tests. If a single target '
             'in a test run has no timeout and there is no default, the entire run will have no timeout. This '
             'should change in the future to provide more granularity.')
    register('--timeout-default', action='store', type=int, advanced=True,
             help='The default timeout (in seconds) for a test if timeout is not set on the target.')
    register('--timeout-maximum', action='store', type=int, advanced=True,
             help='The maximum timeout (in seconds) that can be set on a test target.')

  def execute(self):
    """Run the task."""

    # Ensure that the timeout_maximum is higher than the timeout default.
    if (self.get_options().timeout_maximum is not None
        and self.get_options().timeout_default is not None
        and self.get_options().timeout_maximum < self.get_options().timeout_default):
      message = "Error: timeout-default: {} exceeds timeout-maximum: {}".format(
        self.get_options().timeout_maximum,
        self.get_options().timeout_default
      )
      self.context.log.error(message)
      raise TestFailedTaskError(message)

    if not self.get_options().skip:
      test_targets = self._get_test_targets()
      all_targets = self._get_targets()
      for target in test_targets:
        self._validate_target(target)

      timeout = self._timeout_for_targets(test_targets)

      try:
        with Timeout(timeout, abort_handler=self._timeout_abort_handler):
          self._execute(all_targets)
      except TimeoutReached as e:
        raise TestFailedTaskError(str(e), failed_targets=test_targets)

  def _timeout_for_target(self, target):
    timeout = getattr(target, 'timeout', None)
    deprecated_conditional(
      lambda: timeout == 0,
      "0.0.65",
      hint_message=dedent("""
        Target {target} has parameter: 'timeout=0', which is deprecated.
        To use the default timeout remove the 'timeout' parameter from your test target.
      """.format(target=target.address.spec)))

    timeout_maximum = self.get_options().timeout_maximum
    if timeout is not None and timeout_maximum is not None:
      if timeout > timeout_maximum:
        self.context.log.warn(
          "Warning: Timeout for {target} ({timeout}s) exceeds {timeout_maximum}s. Capping.".format(
            target=target.address.spec,
            timeout=timeout,
            timeout_maximum=timeout_maximum))
        return timeout_maximum

    return timeout

  def _timeout_for_targets(self, targets):
    """Calculate the total timeout based on the timeout configuration for all the targets.

    Because the timeout wraps all the test targets rather than individual tests, we have to somehow
    aggregate all the target specific timeouts into one value that will cover all the tests. If some targets
    have no timeout configured (or set to 0), their timeout will be set to the default timeout.
    If there is no default timeout, or if it is set to zero, there will be no timeout, if any of the test targets
    have a timeout set to 0 or no timeout configured.

    TODO(sbrenn): This behavior where timeout=0 is the same as timeout=None has turned out to be very confusing,
    and should change so that timeout=0 actually sets the timeout to 0, and only timeout=None
    should set the timeout to the default timeout. This will require a deprecation cycle.

    :param targets: list of test targets
    :return: timeout to cover all the targets, in seconds
    """

    if not self.get_options().timeouts:
      return None

    timeout_default = self.get_options().timeout_default

    # Gather up all the timeouts.
    timeouts = [self._timeout_for_target(target) for target in targets]

    # If any target's timeout is None or 0, then set it to the default timeout.
    # TODO(sbrenn): Change this so that only if the timeout is None, set it to default timeout.
    timeouts_w_default = [timeout or timeout_default for timeout in timeouts]

    # Even after we've done that, there may be a 0 or None in the timeout list if the
    # default timeout is set to 0 or None. So if that's the case, then the timeout is
    # disabled.
    # TODO(sbrenn): Change this so that if the timeout is 0, it is actually 0.
    if 0 in timeouts_w_default or None in timeouts_w_default:
      return None
    else:
      # Sum the timeouts for all the targets, using the default timeout where one is not set.
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
  def _timeout_abort_handler(self):
    """Abort the test process when it has been timed out."""

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
