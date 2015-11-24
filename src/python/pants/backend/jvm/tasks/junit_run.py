# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import os
import sys
from collections import defaultdict

from six.moves import range
from twitter.common.collections import OrderedSet

from pants.backend.core.tasks.test_task_mixin import TestTaskMixin
from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.java_tests import JavaTests as junit_tests
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.coverage.base import Coverage
from pants.backend.jvm.tasks.coverage.cobertura import Cobertura, CoberturaTaskSettings
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException, TaskError, TestFailedTaskError
from pants.base.revision import Revision
from pants.base.workunit import WorkUnitLabel
from pants.binaries import binary_util
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.util.strutil import pluralize
from pants.util.xml_parser import XmlParser


# TODO(ji): Add unit tests.
def _classfile_to_classname(cls):
  return ClasspathUtil.classname_for_rel_classfile(cls)


def interpret_test_spec(test_spec):
  """Parses a test spec string.

  Returns either a (sourcefile,method) on the left, or a (classname,method) on the right.
  """
  components = test_spec.split('#', 2)
  classname_or_srcfile = components[0]
  methodname = '#' + components[1] if len(components) == 2 else ''

  if os.path.exists(classname_or_srcfile):
    # It's a source file.
    return ((classname_or_srcfile, methodname), None)
  else:
    # It's a classname.
    return (None, (classname_or_srcfile, methodname))


class JUnitRun(TestTaskMixin, JvmToolTaskMixin, JvmTask):
  _MAIN = 'org.pantsbuild.tools.junit.ConsoleRunner'

  @classmethod
  def register_options(cls, register):
    super(JUnitRun, cls).register_options(register)
    register('--batch-size', advanced=True, type=int, default=sys.maxint,
             help='Run at most this many tests in a single test process.')
    register('--test', action='append',
             help='Force running of just these tests.  Tests can be specified using any of: '
                  '[classname], [classname]#[methodname], [filename] or [filename]#[methodname]')
    register('--per-test-timer', action='store_true', help='Show progress and timer for each test.')
    register('--default-parallel', advanced=True, action='store_true',
             help='Run classes without @TestParallel or @TestSerial annotations in parallel.')
    register('--parallel-threads', advanced=True, type=int, default=0,
             help='Number of threads to run tests in parallel. 0 for autoset.')
    register('--test-shard', advanced=True,
             help='Subset of tests to run, in the form M/N, 0 <= M < N. '
                  'For example, 1/3 means run tests number 2, 5, 8, 11, ...')
    register('--suppress-output', action='store_true', default=True,
             deprecated_hint='Use --output-mode instead.',
             deprecated_version='0.0.64',
             help='Redirect test output to files in .pants.d/test/junit.')
    register('--output-mode', choices=['ALL', 'FAILURE_ONLY', 'NONE'], default='NONE',
             help='Specify what part of output should be passed to stdout. '
                  'In case of FAILURE_ONLY and parallel tests execution '
                  'output can be partial or even wrong. '
                  'All tests output also redirected to files in .pants.d/test/junit.')
    register('--cwd', advanced=True,
             help='Set the working directory. If no argument is passed, use the build root. '
                  'If cwd is set on a target, it will supersede this argument.')
    register('--strict-jvm-version', action='store_true', default=False, advanced=True,
             help='If true, will strictly require running junits with the same version of java as '
                  'the platform -target level. Otherwise, the platform -target level will be '
                  'treated as the minimum jvm to run.')
    register('--failure-summary', action='store_true', default=True,
             help='If true, includes a summary of which test-cases failed at the end of a failed '
                  'junit run.')
    register('--allow-empty-sources', action='store_true', default=False, advanced=True,
             help='Allows a junit_tests() target to be defined with no sources.  Otherwise,'
                  'such a target will raise an error during the test run.')
    cls.register_jvm_tool(register,
                          'junit',
                          classpath=[
                            JarDependency(org='org.pantsbuild', name='junit-runner', rev='0.0.13'),
                          ],
                          main=JUnitRun._MAIN,
                          # TODO(John Sirois): Investigate how much less we can get away with.
                          # Clearly both tests and the runner need access to the same @Test,
                          # @Before, as well as other annotations, but there is also the Assert
                          # class and some subset of the @Rules, @Theories and @RunWith APIs.
                          custom_rules=[
                            Shader.exclude_package('junit.framework', recursive=True),
                            Shader.exclude_package('org.junit', recursive=True),
                            Shader.exclude_package('org.hamcrest', recursive=True),
                            Shader.exclude_package('org.pantsbuild.junit.annotations', recursive=True),
                          ])
    # TODO: Yuck, but will improve once coverage steps are in their own tasks.
    for c in [Coverage, Cobertura]:
      c.register_options(register, cls.register_jvm_tool)

  @classmethod
  def subsystem_dependencies(cls):
    return super(JUnitRun, cls).subsystem_dependencies() + (DistributionLocator,)

  @classmethod
  def request_classes_by_source(cls, test_specs):
    """Returns true if the given test specs require the `classes_by_source` product to satisfy."""
    for test_spec in test_specs:
      src_spec, _ = interpret_test_spec(test_spec)
      if src_spec:
        return True
    return False

  @classmethod
  def prepare(cls, options, round_manager):
    super(JUnitRun, cls).prepare(options, round_manager)

    # Compilation and resource preparation must have completed.
    round_manager.require_data('runtime_classpath')

    # If the given test specs require the classes_by_source product, request it.
    if cls.request_classes_by_source(options.test or []):
      round_manager.require_data('classes_by_source')

  def __init__(self, *args, **kwargs):
    super(JUnitRun, self).__init__(*args, **kwargs)

    options = self.get_options()
    self._coverage = None
    if options.coverage or options.is_flagged('coverage_open'):
      coverage_processor = options.coverage_processor
      if coverage_processor == 'cobertura':
        settings = CoberturaTaskSettings(self)
        self._coverage = Cobertura(settings)
      else:
        raise TaskError('unknown coverage processor {0}'.format(coverage_processor))

    self._tests_to_run = options.test
    self._batch_size = options.batch_size
    self._fail_fast = options.fail_fast
    self._working_dir = options.cwd or get_buildroot()
    self._strict_jvm_version = options.strict_jvm_version
    self._args = copy.copy(self.args)
    self._failure_summary = options.failure_summary

    if (not options.suppress_output) or options.output_mode == 'ALL':
      self._args.append('-output-mode=ALL')
    elif options.output_mode == 'FAILURE_ONLY':
      self._args.append('-output-mode=FAILURE_ONLY')
    else:
      self._args.append('-output-mode=NONE')

    if self._fail_fast:
      self._args.append('-fail-fast')
    self._args.append('-outdir')
    self._args.append(self.workdir)

    if options.per_test_timer:
      self._args.append('-per-test-timer')
    if options.default_parallel:
      self._args.append('-default-parallel')
    self._args.append('-parallel-threads')
    self._args.append(str(options.parallel_threads))

    if options.test_shard:
      self._args.append('-test-shard')
      self._args.append(options.test_shard)

    self._executor = None

  def preferred_jvm_distribution_for_targets(self, targets):
    return self.preferred_jvm_distribution([target.platform for target in targets
                                            if isinstance(target, JvmTarget)])

  def preferred_jvm_distribution(self, platforms):
    """Returns a jvm Distribution with a version that should work for all the platforms."""
    if not platforms:
      return DistributionLocator.cached()
    min_version = max(platform.target_level for platform in platforms)
    max_version = Revision(*(min_version.components + [9999])) if self._strict_jvm_version else None
    return DistributionLocator.cached(minimum_version=min_version, maximum_version=max_version)

  def execute_java_for_targets(self, targets, executor=None, *args, **kwargs):
    distribution = self.preferred_jvm_distribution_for_targets(targets)
    self._executor = executor or SubprocessExecutor(distribution)
    return distribution.execute_java(*args, executor=self._executor, **kwargs)

  def _collect_test_targets(self, targets):
    """Returns a mapping from test names to target objects for all tests that
    are included in targets. If self._tests_to_run is set, return {test: None}
    for these tests instead.
    """

    tests_from_targets = dict(list(self._calculate_tests_from_targets(targets)))

    if targets and self._tests_to_run:
      # If there are some junit_test targets in the graph, find ones that match the requested
      # test(s).
      tests_with_targets = {}
      unknown_tests = []
      for test in self._get_tests_to_run():
        # A test might contain #specific_method, which is not needed to find a target.
        test_class_name = test.partition('#')[0]
        target = tests_from_targets.get(test_class_name)
        if target is None:
          unknown_tests.append(test)
        else:
          tests_with_targets[test] = target

      if len(unknown_tests) > 0:
        raise TaskError("No target found for test specifier(s):\n\n  '{}'\n\nPlease change " \
                        "specifier or bring in the proper target(s)."
                        .format("'\n  '".join(unknown_tests)))

      return tests_with_targets
    else:
      return tests_from_targets

  def _get_failed_targets(self, tests_and_targets):
    """Return a mapping of target -> set of individual test cases that failed.

    Targets with no failed tests are omitted.

    Analyzes JUnit XML files to figure out which test had failed.

    The individual test cases are formatted strings of the form org.foo.bar.classname#methodName.

    :tests_and_targets: {test: target} mapping.
    """

    def get_test_filename(test):
      return os.path.join(self.workdir, 'TEST-{0}.xml'.format(test))

    failed_targets = defaultdict(set)

    for test, target in tests_and_targets.items():
      if target is None:
        self.context.log.warn('Unknown target for test %{0}'.format(test))

      filename = get_test_filename(test)

      if os.path.exists(filename):
        try:
          xml = XmlParser.from_file(filename)
          str_failures = xml.get_attribute('testsuite', 'failures')
          int_failures = int(str_failures)

          str_errors = xml.get_attribute('testsuite', 'errors')
          int_errors = int(str_errors)

          if target and (int_failures or int_errors):
            for testcase in xml.parsed.getElementsByTagName('testcase'):
              test_failed = testcase.getElementsByTagName('failure')
              test_errored = testcase.getElementsByTagName('error')
              if test_failed or test_errored:
                failed_targets[target].add('{testclass}#{testname}'.format(
                  testclass=testcase.getAttribute('classname'),
                  testname=testcase.getAttribute('name'),
                ))
        except (XmlParser.XmlError, ValueError) as e:
          self.context.log.error('Error parsing test result file {0}: {1}'.format(filename, e))

    return dict(failed_targets)

  def _run_tests(self, tests_to_targets):

    if self._coverage:
      extra_jvm_options = self._coverage.extra_jvm_options
      classpath_prepend = self._coverage.classpath_prepend
      classpath_append = self._coverage.classpath_append
    else:
      extra_jvm_options = []
      classpath_prepend = ()
      classpath_append = ()

    tests_by_properties = self._tests_by_properties(tests_to_targets,
                                                    self._infer_workdir,
                                                    lambda target: target.test_platform)

    # the below will be None if not set, and we'll default back to runtime_classpath
    classpath_product = self.context.products.get_data('instrument_classpath')

    result = 0
    for (workdir, platform), tests in tests_by_properties.items():
      for (target_jvm_options, target_tests) in self._partition_by_jvm_options(tests_to_targets,
                                                                               tests):
        for batch in self._partition(target_tests):
          # Batches of test classes will likely exist within the same targets: dedupe them.
          relevant_targets = set(map(tests_to_targets.get, batch))
          complete_classpath = OrderedSet()
          complete_classpath.update(classpath_prepend)
          complete_classpath.update(self.tool_classpath('junit'))
          complete_classpath.update(self.classpath(relevant_targets,
                                                   classpath_product=classpath_product))
          complete_classpath.update(classpath_append)
          distribution = self.preferred_jvm_distribution([platform])
          with binary_util.safe_args(batch, self.get_options()) as batch_tests:
            self.context.log.debug('CWD = {}'.format(workdir))
            self.context.log.debug('platform = {}'.format(platform))
            self._executor = SubprocessExecutor(distribution)
            result += abs(distribution.execute_java(
              executor=self._executor,
              classpath=complete_classpath,
              main=JUnitRun._MAIN,
              jvm_options=self.jvm_options + extra_jvm_options + target_jvm_options,
              args=self._args + batch_tests + [u'-xmlreport'],
              workunit_factory=self.context.new_workunit,
              workunit_name='run',
              workunit_labels=[WorkUnitLabel.TEST],
              cwd=workdir,
              synthetic_jar_dir=self.workdir,
            ))

            if result != 0 and self._fail_fast:
              break

    if result != 0:
      failed_targets_and_tests = self._get_failed_targets(tests_to_targets)
      failed_targets = sorted(failed_targets_and_tests, key=lambda target: target.address.spec)
      error_message_lines = []
      if self._failure_summary:
        for target in failed_targets:
          error_message_lines.append('\n{0}{1}'.format(' '*4, target.address.spec))
          for test in sorted(failed_targets_and_tests[target]):
            error_message_lines.append('{0}{1}'.format(' '*8, test))
      error_message_lines.append(
        '\njava {main} ... exited non-zero ({code}); {failed} failed {targets}.'
          .format(main=JUnitRun._MAIN, code=result, failed=len(failed_targets),
                  targets=pluralize(len(failed_targets), 'target'))
      )
      raise TestFailedTaskError('\n'.join(error_message_lines), failed_targets=list(failed_targets))

  def _infer_workdir(self, target):
    if target.cwd is not None:
      return target.cwd
    return self._working_dir

  def _tests_by_property(self, tests_to_targets, get_property):
    properties = defaultdict(OrderedSet)
    for test, target in tests_to_targets.items():
      properties[get_property(target)].add(test)
    return {property: list(tests) for property, tests in properties.items()}

  def _tests_by_properties(self, tests_to_targets, *properties):
    def combined_property(target):
      return tuple(prop(target) for prop in properties)

    return self._tests_by_property(tests_to_targets, combined_property)

  def _partition_by_jvm_options(self, tests_to_targets, tests):
    """Partitions a list of tests by the jvm options to run them with.

    :param dict tests_to_target: A mapping from each test to its target.
    :param list tests: The list of tests to run.
    :returns: A list of tuples where the first element is an array of jvm options and the second
      is a list of tests to run with the jvm options. Each test in tests will appear in exactly
      one one tuple.
    """
    jvm_options_to_tests = defaultdict(list)
    for test in tests:
      extra_jvm_options = tests_to_targets[test].payload.extra_jvm_options
      jvm_options_to_tests[extra_jvm_options].append(test)
    return [(list(jvm_options), tests) for jvm_options, tests in jvm_options_to_tests.items()]

  def _partition(self, tests):
    stride = min(self._batch_size, len(tests))
    for i in range(0, len(tests), stride):
      yield tests[i:i + stride]

  def _get_tests_to_run(self):
    for test_spec in self._tests_to_run:
      src_spec, cls_spec = interpret_test_spec(test_spec)
      if src_spec:
        sourcefile, methodname = src_spec
        for classname in self._classnames_from_source_file(sourcefile):
          # Tack the methodname onto all classes in the source file, as we
          # can't know which method the user intended.
          yield classname + methodname
      else:
        classname, methodname = cls_spec
        yield classname + methodname

  def _calculate_tests_from_targets(self, targets):
    """
    :param list targets: list of targets to calculate test classes for.
    generates tuples (class_name, target).
    """
    classpath_products = self.context.products.get_data('runtime_classpath')
    for target in targets:
      contents = ClasspathUtil.classpath_contents((target,), classpath_products, confs=self.confs)
      for f in contents:
        classname = ClasspathUtil.classname_for_rel_classfile(f)
        if classname:
          yield (classname, target)

  def _classnames_from_source_file(self, srcfile):
    relsrc = os.path.relpath(srcfile, get_buildroot())
    source_products = self.context.products.get_data('classes_by_source').get(relsrc)
    if not source_products:
      # It's valid - if questionable - to have a source file with no classes when, for
      # example, the source file has all its code commented out.
      self.context.log.warn('Source file {0} generated no classes'.format(srcfile))
    else:
      for _, classes in source_products.rel_paths():
        for cls in classes:
          yield _classfile_to_classname(cls)

  def _test_target_filter(self):
    def target_filter(target):
      return isinstance(target, junit_tests)
    return target_filter

  def _validate_target(self, target):
    # TODO: move this check to an optional phase in goal_runner, so
    # that missing sources can be detected early.
    if not target.payload.sources.source_paths and not self.get_options().allow_empty_sources:
      msg = 'JavaTests target must include a non-empty set of sources.'
      raise TargetDefinitionException(target, msg)

  def _timeout_abort_handler(self):
    """Kills the test run."""

    # TODO(sameerbrenn): When we refactor the test code to be more standardized, rather than
    #   storing the process handle here, the test mixin class will call the start_test() fn
    #   on the language specific class which will return an object that can kill/monitor/etc
    #   the test process.
    if self._executor is not None:
      self._executor.kill()

  def _execute(self, targets):
    """
    Implements the primary junit test execution. This method is called by the TestTaskMixin,
    which contains the primary Task.execute function and wraps this method in timeouts.
    """

    # We only run tests within java_tests/junit_tests targets.
    #
    # But if coverage options are specified, we want to instrument
    # and report on all the original targets, not just the test targets.
    #
    # We've already filtered out the non-test targets in the
    # TestTaskMixin, so the mixin passes to us both the test
    # targets and the unfiltered list of targets
    tests_and_targets = self._collect_test_targets(self._get_test_targets())

    if not tests_and_targets:
      return

    bootstrapped_cp = self.tool_classpath('junit')

    def compute_complete_classpath():
      return self.classpath(targets)

    self.context.release_lock()
    if self._coverage:
      self._coverage.instrument(
        targets, tests_and_targets.keys(), compute_complete_classpath, self.execute_java_for_targets)

    def _do_report(exception=None):
      if self._coverage:
        self._coverage.report(
          targets, tests_and_targets.keys(), self.execute_java_for_targets, tests_failed_exception=exception)

    try:
      self._run_tests(tests_and_targets)
      _do_report(exception=None)
    except TaskError as e:
      _do_report(exception=e)
      raise
