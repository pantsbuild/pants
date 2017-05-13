# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from abc import abstractmethod
from threading import Timer

from pants.base.exceptions import ErrorWhileTesting
from pants.util.timeout import Timeout, TimeoutReached
from pants.util.xml_parser import XmlParser


class TestRunnerTaskMixin(object):
  """A mixin to combine with test runner tasks.

  The intent is to migrate logic over time out of JUnitRun and PytestRun, so the functionality
  expressed can support both languages, and any additional languages that are added to pants.
  """

  @classmethod
  def register_options(cls, register):
    super(TestRunnerTaskMixin, cls).register_options(register)
    register('--skip', type=bool, help='Skip running tests.')
    register('--timeouts', type=bool, default=True,
             help='Enable test target timeouts. If timeouts are enabled then tests with a '
                  'timeout= parameter set on their target will time out after the given number of '
                  'seconds if not completed. If no timeout is set, then either the default timeout '
                  'is used or no timeout is configured. In the current implementation, all the '
                  'timeouts for the test targets to be run are summed and all tests are run with '
                  'the total timeout covering the entire run of tests. If a single target in a '
                  'test run has no timeout and there is no default, the entire run will have no '
                  'timeout. This should change in the future to provide more granularity.')
    register('--timeout-default', type=int, advanced=True,
             help='The default timeout (in seconds) for a test if timeout is not set on the '
                  'target.')
    register('--timeout-maximum', type=int, advanced=True,
             help='The maximum timeout (in seconds) that can be set on a test target.')
    register('--timeout-terminate-wait', type=int, advanced=True, default=10,
             help='If a test does not terminate on a SIGTERM, how long to wait (in seconds) before '
                  'sending a SIGKILL.')

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
      raise ErrorWhileTesting(message)

    if not self.get_options().skip:
      test_targets = self._get_test_targets()
      for target in test_targets:
        self._validate_target(target)

      all_targets = self._get_targets()
      self._execute(all_targets)

  def report_test_info(self, scope, target, test_name, test_info):
    """Add test information to target information.

    :param string scope: The scope for which we are reporting information.
    :param Target target: The target that we want to store the test information under.
    :param string test_name: The key (test name) for the information being stored.
    :param dict test_info: The information being stored.
    """
    if target and scope:
      address = target.address.spec
      target_type = target.type_alias
      self.context.run_tracker.report_target_info('GLOBAL', address, 'target_type', target_type)
      self.context.run_tracker.report_target_info(scope, address, test_name, test_info)

  @staticmethod
  def parse_test_info(xml_path, error_handler, additional_testcase_attributes=None):
    """Parses the junit file for information needed about each test.

    Will include:
      - test result
      - test run time duration
      - test name
    :param string xml_path: The path of the xml file to be parsed.
    :param function error_handler: The error handler function.
    :param list of string additional_testcase_attributes: A list of additional attributes belonging
           to each testcase that should be included in test information.
    :return: A dictionary of test information.
    """
    tests_in_path = {}
    testcase_attributes = additional_testcase_attributes or []

    SUCCESS = 'success'
    SKIPPED = 'skipped'
    FAILURE = 'failure'
    ERROR = 'error'

    _XML_MATCHER = re.compile(r'^TEST-.+\.xml$')

    class ParseError(Exception):
      """Indicates an error parsing a xml report file."""

      def __init__(self, xml_path, cause):
        super(ParseError, self).__init__('Error parsing test result file {}: {}'
          .format(xml_path, cause))
        self.xml_path = xml_path
        self.cause = cause

    def parse_xml_file(path):
      try:
        xml = XmlParser.from_file(path)
        for testcase in xml.parsed.getElementsByTagName('testcase'):
          test_info = {'time': float(testcase.getAttribute('time'))}
          for attribute in testcase_attributes:
            test_info[attribute] = testcase.getAttribute(attribute)

          test_error = testcase.getElementsByTagName('error')
          test_fail = testcase.getElementsByTagName('failure')
          test_skip = testcase.getElementsByTagName('skipped')

          if test_fail:
            test_info.update({'result_code': FAILURE})
          elif test_error:
            test_info.update({'result_code': ERROR})
          elif test_skip:
            test_info.update({'result_code': SKIPPED})
          else:
            test_info.update({'result_code': SUCCESS})

          tests_in_path.update({testcase.getAttribute('name'): test_info})

      except (XmlParser.XmlError, ValueError) as e:
        error_handler(ParseError(path, e))

    if os.path.isdir(xml_path):
      for name in os.listdir(xml_path):
        if _XML_MATCHER.match(name):
          parse_xml_file(os.path.join(xml_path, name))
    else:
      parse_xml_file(xml_path)

    return tests_in_path

  def _get_test_targets_for_spawn(self):
    """Invoked by _spawn_and_wait to know targets being executed. Defaults to _get_test_targets().

    _spawn_and_wait passes all its arguments through to _spawn, but it needs to know what targets
    are being executed by _spawn. A caller to _spawn_and_wait can override this method to return
    the targets being executed by the current _spawn_and_wait. By default it returns
    _get_test_targets(), which is all test targets.
    """
    return self._get_test_targets()

  def _spawn_and_wait(self, *args, **kwargs):
    """Spawn the actual test runner process, and wait for it to complete."""

    test_targets = self._get_test_targets_for_spawn()
    timeout = self._timeout_for_targets(test_targets)

    process_handler = self._spawn(*args, **kwargs)

    def _graceful_terminate(handler, wait_time):
      """
      Returns a function which attempts to terminate the process gracefully.

      If terminate doesn't work after wait_time seconds, do a kill.
      """

      def terminator():
        handler.terminate()
        def kill_if_not_terminated():
          if handler.poll() is None:
            # We can't use the context logger because it might not exist.
            import logging
            logger = logging.getLogger(__name__)
            logger.warn('Timed out test did not terminate gracefully after {} seconds, killing...'
                        .format(wait_time))
            handler.kill()

        timer = Timer(wait_time, kill_if_not_terminated)
        timer.start()

      return terminator

    try:
      with Timeout(timeout,
                   threading_timer=Timer,
                   abort_handler=_graceful_terminate(process_handler,
                                                     self.get_options().timeout_terminate_wait)):
        return process_handler.wait()
    except TimeoutReached as e:
      raise ErrorWhileTesting(str(e), failed_targets=test_targets)

  @abstractmethod
  def _spawn(self, *args, **kwargs):
    """Spawn the actual test runner process.

    :rtype: ProcessHandler
    """

    raise NotImplementedError

  def _timeout_for_target(self, target):
    timeout = getattr(target, 'timeout', None)
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
    aggregate all the target specific timeouts into one value that will cover all the tests. If some
    targets have no timeout configured (or set to 0), their timeout will be set to the default
    timeout. If there is no default timeout, or if it is set to zero, there will be no timeout, if
    any of the test targets have a timeout set to 0 or no timeout configured.

    TODO(sbrenn): This behavior where timeout=0 is the same as timeout=None has turned out to be
    very confusing, and should change so that timeout=0 actually sets the timeout to 0, and only
    timeout=None should set the timeout to the default timeout. This will require a deprecation
    cycle.

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
  def _test_target_filter(self):
    """A filter to run on targets to see if they are relevant to this test task.

    :return: function from target->boolean
    """
    raise NotImplementedError

  @abstractmethod
  def _validate_target(self, target):
    """Ensures that this target is valid. Raises TargetDefinitionException if the target is invalid.

    We don't need the type check here because _get_targets() combines with _test_target_type to
    filter the list of targets to only the targets relevant for this test task.

    :param target: the target to validate
    :raises: TargetDefinitionException
    """
    raise NotImplementedError

  @abstractmethod
  def _execute(self, all_targets):
    """Actually goes ahead and runs the tests for the targets.

    :param all_targets: list of the targets whose tests are to be run
    """
    raise NotImplementedError
