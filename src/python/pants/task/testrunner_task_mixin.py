# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import xml.etree.ElementTree as ET
from abc import abstractmethod
from threading import Timer

from pants.base.exceptions import ErrorWhileTesting, TaskError
from pants.build_graph.files import Files
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.task.task import Task
from pants.util.memo import memoized_method, memoized_property
from pants.util.process_handler import subprocess


class TestResult(object):
  @classmethod
  @memoized_method
  def successful(cls):
    return cls.rc(0)

  @classmethod
  @memoized_method
  def exception(cls):
    return cls('EXCEPTION')

  @classmethod
  def _map_exit_code(cls, value):
    """Potentially transform test process exit codes.

    Subclasses can override this classmethod if they know the test process emits non-standard
    success (0) error codes. By default, no mapping is done and the `value` simply passes through.

    :param int value: The test process exit code.
    :returns: A potentially re-mapped exit code.
    :rtype: int
    """
    return value

  @classmethod
  def rc(cls, value):
    exit_code = cls._map_exit_code(value)
    return cls('SUCCESS' if exit_code == 0 else 'FAILURE', rc=exit_code)

  @classmethod
  def from_error(cls, error):
    if not isinstance(error, TaskError):
      raise AssertionError('Can only synthesize a {} from a TaskError, given a {}'
                           .format(cls.__name__, type(error).__name__))
    return cls(str(error), rc=error.exit_code, failed_targets=error.failed_targets)

  def with_failed_targets(self, failed_targets):
    return self.__class__(self._msg, self._rc, failed_targets)

  def __init__(self, msg, rc=None, failed_targets=None):
    self._rc = rc
    self._msg = msg
    self._failed_targets = failed_targets or []

  def __str__(self):
    return self._msg

  @property
  def success(self):
    return self._rc == 0

  @property
  def failed_targets(self):
    return self._failed_targets

  def checked(self):
    """Raise if this result was unsuccessful and otherwise return this result unchanged.

    :returns: this instance if successful
    :rtype: :class:`TestResult`
    :raises: :class:`ErrorWhileTesting` if this result represents a failure
    """
    if not self.success:
      raise ErrorWhileTesting(self._msg,
                              exit_code=self._rc,
                              failed_targets=self._failed_targets)
    return self


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

  def report_all_info_for_single_test(self, scope, target, test_name, test_info):
    """Add all of the test information for a single test.

    Given the dict of test information
    {'time': 0.124, 'result_code': 'success', 'classname': 'some.test.class'}
    iterate through each item and report the single item with _report_test_info.

    :param string scope: The scope for which we are reporting the information.
    :param Target target: The target that we want to store the test information under.
    :param string test_name: The test's name.
    :param dict test_info: The test's information, including run duration and result.
    """
    for test_info_key, test_info_val in test_info.items():
      key_list = [test_name, test_info_key]
      self._report_test_info(scope, target, key_list, test_info_val)

  def _report_test_info(self, scope, target, keys, test_info):
    """Add test information to target information.

    :param string scope: The scope for which we are reporting information.
    :param Target target: The target that we want to store the test information under.
    :param list of string keys: The keys that will point to the information being stored.
    :param primitive test_info: The information being stored.
    """
    if target and scope:
      target_type = target.type_alias
      self.context.run_tracker.report_target_info('GLOBAL', target, ['target_type'], target_type)
      self.context.run_tracker.report_target_info(scope, target, keys, test_info)

  @staticmethod
  def parse_test_info(xml_path, error_handler, additional_testcase_attributes=None):
    """Parses the junit file for information needed about each test.

    Will include:
      - test name
      - test result
      - test run time duration or None if not a parsable float

    If additional test case attributes are defined, then it will include those as well.

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

    def parse_xml_file(xml_file_path):
      try:
        root = ET.parse(xml_file_path).getroot()
        for testcase in root.iter('testcase'):
          test_info = {}

          try:
            test_info.update({'time': float(testcase.attrib.get('time'))})
          except (TypeError, ValueError):
            test_info.update({'time': None})

          for attribute in testcase_attributes:
            test_info[attribute] = testcase.attrib.get(attribute)

          result = SUCCESS
          if next(testcase.iter('error'), None) is not None:
            result = ERROR
          elif next(testcase.iter('failure'), None) is not None:
            result = FAILURE
          elif next(testcase.iter('skipped'), None) is not None:
            result = SKIPPED
          test_info.update({'result_code': result})

          tests_in_path.update({testcase.attrib.get('name', ''): test_info})

      except (ET.ParseError, ValueError) as e:
        error_handler(ParseError(xml_file_path, e))

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

    def maybe_terminate(wait_time):
      if process_handler.poll() < 0:
        process_handler.terminate()

        def kill_if_not_terminated():
          if process_handler.poll() < 0:
            # We can't use the context logger because it might not exist when this delayed function
            # is executed by the Timer below.
            import logging
            logger = logging.getLogger(__name__)
            logger.warn('Timed out test did not terminate gracefully after {} seconds, killing...'
                        .format(wait_time))
            process_handler.kill()

        timer = Timer(wait_time, kill_if_not_terminated)
        timer.start()

    try:
      return process_handler.wait(timeout=timeout)
    except subprocess.TimeoutExpired as e:
      # Since we no longer surface the actual underlying exception, we log.error here
      # to ensure the output indicates why the test has suddenly failed.
      self.context.log.error('FAILURE: Timeout of {} seconds reached.'.format(timeout))
      raise ErrorWhileTesting(str(e), failed_targets=test_targets)
    finally:
      maybe_terminate(wait_time=self.get_options().timeout_terminate_wait)

  @abstractmethod
  def _spawn(self, *args, **kwargs):
    """Spawn the actual test runner process.

    :rtype: ProcessHandler
    """

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


class PartitionedTestRunnerTaskMixin(TestRunnerTaskMixin, Task):
  """A mixin for test tasks that support running tests over both individual targets and batches.

  Provides support for partitioning via `--fast` (batches) and `--no-fast` (per target) options and
  helps ensure correct caching behavior in either mode.

  It's expected that mixees implement proper chrooting (see `run_tests_in_chroot`) to support
  correct successful test result caching.
  """

  @classmethod
  def register_options(cls, register):
    super(PartitionedTestRunnerTaskMixin, cls).register_options(register)

    # TODO(John Sirois): Implement sanity checks on options wrt caching:
    # https://github.com/pantsbuild/pants/issues/5073

    register('--fast', type=bool, default=True, fingerprint=True,
             help='Run all tests in a single pytest invocation. If turned off, each test target '
                  'will run in its own pytest invocation, which will be slower, but isolates '
                  'tests from process-wide state created by tests in other targets.')
    register('--chroot', advanced=True, fingerprint=True, type=bool, default=False,
             help='Run tests in a chroot. Any loose files tests depend on via `{}` dependencies '
                  'will be copied to the chroot.'
             .format(Files.alias()))

  @staticmethod
  def _vts_for_partition(invalidation_check):
    return VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)

  def check_artifact_cache_for(self, invalidation_check):
    # Tests generate artifacts, namely junit.xml and coverage reports, that cover the full target
    # set whether that is all targets in the context (`--fast`) or each target individually
    # (`--no-fast`).
    return [self._vts_for_partition(invalidation_check)]

  @property
  def run_tests_in_chroot(self):
    """Return `True` if tests should be run in a chroot.

    Chrooted tests are expected to be run with $PWD set to a directory with only files explicitly
    (transitively) depended on by the test targets present.

    :rtype: bool
    """
    return self.get_options().chroot

  def _execute(self, all_targets):
    test_targets = self._get_test_targets()
    if not test_targets:
      return

    self.context.release_lock()

    per_target = not self.get_options().fast
    fail_fast = self.get_options().fail_fast

    results = {}
    failure = False
    with self.partitions(per_target, all_targets, test_targets) as partitions:
      for (partition, args) in partitions():
        try:
          rv = self._run_partition(fail_fast, partition, *args)
        except ErrorWhileTesting as e:
          rv = self.result_class.from_error(e)

        results[partition] = rv
        if not rv.success:
          failure = True
          if fail_fast:
            break

      for partition in sorted(results):
        rv = results[partition]
        failed_targets = set(rv.failed_targets)
        for target in partition:
          if target in failed_targets:
            log = self.context.log.error
            result = rv
          else:
            log = self.context.log.info
            result = self.result_class.successful()
          log('{0:80}.....{1:>10}'.format(target.address.reference(), result))

      msgs = [str(_rv) for _rv in results.values() if not _rv.success]
      failed_targets = [target
                        for _rv in results.values() if not _rv.success
                        for target in _rv.failed_targets]
      if len(failed_targets) > 0:
        raise ErrorWhileTesting('\n'.join(msgs), failed_targets=failed_targets)
      elif failure:
        # A low-level test execution failure occurred before tests were run.
        raise TaskError()

  # Some notes on invalidation vs caching as used in `run_partition` below. Here invalidation
  # refers to executing task work in `Task.invalidated` blocks against invalid targets. Caching
  # refers to storing the results of that work in the artifact cache using
  # `VersionedTargetSet.results_dir`. One further bit of terminology is partition, which is the
  # name for the set of targets passed to the `Task.invalidated` block:
  #
  # + Caching results for len(partition) > 1: This is trivial iff we always run all targets in
  #   the partition, but running just invalid targets in the partition is a nicer experience (you
  #   can whittle away at failures in a loop of `::`-style runs). Running just invalid though
  #   requires being able to merge prior results for the partition; ie: knowing the details of
  #   junit xml, coverage data, or using tools that do, to merge data files. The alternative is
  #   to always run all targets in a partition if even 1 target is invalid. In this way data files
  #   corresponding to the full partition are always generated, and so on a green partition, the
  #   cached data files will always represent the full green run.
  #
  # The compromise taken here is to only cache when `all_vts == invalid_vts`; ie when the partition
  # goes green and the run was against the full partition. A common scenario would then be:
  #
  # 1. Mary makes changes / adds new code and iterates `./pants test tests/python/stuff::`
  #    gradually getting greener until finally all test targets in the `tests/python/stuff::` set
  #    pass. She commits the green change, but there is no cached result for it since green state
  #    for the partition was approached incrementally.
  # 2. Jake pulls in Mary's green change and runs `./pants test tests/python/stuff::`. There is a
  #    cache miss and he does a full local run, but since `tests/python/stuff::` is green,
  #    `all_vts == invalid_vts` and the result is now cached for others.
  #
  # In this scenario, Jake will likely be a CI process, in which case human others will see a
  # cached result from Mary's commit. It's important to note, that the CI process must run the same
  # partition as the end user for that end user to benefit and hit the cache. This is unlikely since
  # the only natural partitions under CI are single target ones (`--no-fast` or all targets
  # `--fast ::`. Its unlikely an end user in a large repo will want to run `--fast ::` since `::`
  # is probably a much wider swath of code than they're working on. As such, although `--fast`
  # caching is supported, its unlikely to be effective. Caching is best utilized when CI and users
  # run `--no-fast`.
  def _run_partition(self, fail_fast, test_targets, *args):
    with self.invalidated(targets=test_targets,
                          fingerprint_strategy=self.fingerprint_strategy(),
                          # Re-run tests when the code they test (and depend on) changes.
                          invalidate_dependents=True) as invalidation_check:

      invalid_test_tgts = [invalid_test_tgt
                           for vts in invalidation_check.invalid_vts
                           for invalid_test_tgt in vts.targets]

      # Processing proceeds through:
      # 1.) output -> output_dir
      # 2.) [iff all == invalid] output_dir -> cache: We do this manually for now.
      # 3.) [iff invalid == 0 and all > 0] cache -> workdir: Done transparently by `invalidated`.

      # 1.) Write all results that will be potentially cached to output_dir.
      result = self.run_tests(fail_fast, invalid_test_tgts, *args).checked()

      cache_vts = self._vts_for_partition(invalidation_check)
      if invalidation_check.all_vts == invalidation_check.invalid_vts:
        # 2.) All tests in the partition were invalid, cache successful test results.
        if result.success and self.artifact_cache_writes_enabled():
          self.update_artifact_cache([(cache_vts, self.collect_files(*args))])
      elif not invalidation_check.invalid_vts:
        # 3.) The full partition was valid, our results will have been staged for/by caching
        # if not already local.
        pass
      else:
        # The partition was partially invalid.

        # We don't cache results; so others will need to re-run this partition.
        # NB: We will presumably commit this change now though and so others will get this
        # partition in a state that executes successfully; so when the 1st of the others
        # executes against this partition; they will hit `all_vts == invalid_vts` and
        # cache the results. That 1st of others is hopefully CI!
        cache_vts.force_invalidate()

      return result

  @memoized_property
  def result_class(self):
    """Return the test result type returned by `run_tests`.

    :returns: The test result class to use.
    :rtype: type that is a subclass of :class:`TestResult`
    """
    return TestResult

  def fingerprint_strategy(self):
    """Return a fingerprint strategy for target fingerprinting.

    :returns: A fingerprint strategy instance; by default, `None`; ie let the invalidation and
              caching framework use the default target fingerprinter.
    :rtype: :class:`pants.base.fingerprint_strategy.FingerprintStrategy`
    """
    return None

  @abstractmethod
  def partitions(self, per_target, all_targets, test_targets):
    """Return a context manager that can be called to iterate of target partitions.

    The iterator should return a 2-tuple with the partitions targets in the first slot and a tuple
    of extra arguments needed to `run_tests` and `collect_files`.

    :rtype: A context manager that is callable with no arguments; returning an iterator over
            (partition, tuple(args))
    """

  @abstractmethod
  def run_tests(self, fail_fast, test_targets, *args):
    """Runs tests in the given invalid test targets.

    :param bool fail_fast: `True` if the test run should fail as fast as possible.
    :param test_targets: The test targets to run tests for.
    :type test_targets: list of :class:`pants.build_graph.target.Target`s of the type iterated by
                        `partitions`.
    :param *args: Extra args associated with the partition of test targets being run as returned by
                  the `partitions` iterator.
    :returns: A test result summarizing the result of this test run.
    :rtype: :class:`TestResult`
    """

  @abstractmethod
  def collect_files(self, *args):
    """Collects output files from a test run that should be cached.

    :param *args: Extra args associated with the partition of test targets being run as returned by
                  the `partitions` iterator.
    :returns: A list of paths to files that should be cached.
    :rtype: list of str
    """
