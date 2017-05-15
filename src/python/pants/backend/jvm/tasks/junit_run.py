# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sys
from abc import abstractmethod
from contextlib import contextmanager

from six.moves import range
from twitter.common.collections import OrderedSet

from pants.backend.jvm import argfile
from pants.backend.jvm.subsystems.junit import JUnit
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.coverage.base import Coverage
from pants.backend.jvm.tasks.coverage.cobertura import Cobertura, CoberturaTaskSettings
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.reports.junit_html_report import JUnitHtmlReport
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import ErrorWhileTesting, TargetDefinitionException, TaskError
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.target import Target
from pants.build_graph.target_scopes import Scopes
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.java.junit.junit_xml_parser import RegistryOfTests, Test, parse_failed_targets
from pants.process.lock import OwnerPrintingInterProcessFileLock
from pants.task.testrunner_task_mixin import TestRunnerTaskMixin
from pants.util import desktop
from pants.util.argutil import ensure_arg, remove_arg
from pants.util.contextutil import environment_as
from pants.util.dirutil import safe_mkdir, safe_rmtree
from pants.util.memo import memoized_method
from pants.util.meta import AbstractClass
from pants.util.strutil import pluralize


class _TestSpecification(AbstractClass):
  """Models the string format used to specify which tests to run."""

  @classmethod
  def parse(cls, buildroot, test_spec):
    """Parses a test specification string into an object that can yield corresponding tests.

    Tests can be specified in one of four forms:

    * [classname]
    * [filename]
    * [classname]#[methodname]
    * [filename]#[methodname]

    The first two forms target one or more individual tests contained within a class or file whereas
    the final two forms specify an individual test method to execute.

    :param string buildroot: The path of the current build root directory.
    :param string test_spec: A test specification.
    :returns: A test specification object.
    :rtype: :class:`_TestSpecification`
    """
    components = test_spec.split('#', 2)
    classname_or_sourcefile = components[0]
    methodname = components[1] if len(components) == 2 else None

    if os.path.exists(classname_or_sourcefile):
      sourcefile = os.path.relpath(classname_or_sourcefile, buildroot)
      return _SourcefileSpec(sourcefile=sourcefile, methodname=methodname)
    else:
      return _ClassnameSpec(classname=classname_or_sourcefile, methodname=methodname)

  @abstractmethod
  def iter_possible_tests(self, context):
    """Return an iterator over the possible tests this test specification indicates.

    NB: At least one test yielded by the returned iterator will correspond to an available test,
    but other yielded tests may not exist.

    :param context: The pants execution context.
    :type context: :class:`pants.goal.context.Context`
    :returns: An iterator over possible tests.
    :rtype: iter of :class:`pants.java.junit.junit_xml_parser.Test`
    """


class _SourcefileSpec(_TestSpecification):
  """Models a test specification in [sourcefile]#[methodname] format."""

  def __init__(self, sourcefile, methodname):
    self._sourcefile = sourcefile
    self._methodname = methodname

  def iter_possible_tests(self, context):
    for classname in self._classnames_from_source_file(context):
      # Tack the methodname onto all classes in the source file, as we
      # can't know which method the user intended.
      yield Test(classname=classname, methodname=self._methodname)

  def _classnames_from_source_file(self, context):
    source_products = context.products.get_data('classes_by_source').get(self._sourcefile)
    if not source_products:
      # It's valid - if questionable - to have a source file with no classes when, for
      # example, the source file has all its code commented out.
      context.log.warn('Source file {0} generated no classes'.format(self._sourcefile))
    else:
      for _, classes in source_products.rel_paths():
        for cls in classes:
          yield ClasspathUtil.classname_for_rel_classfile(cls)


class _ClassnameSpec(_TestSpecification):
  """Models a test specification in [classname]#[methodnme] format."""

  def __init__(self, classname, methodname):
    self._classname = classname
    self._methodname = methodname

  def iter_possible_tests(self, context):
    yield Test(classname=self._classname, methodname=self._methodname)


class JUnitRun(TestRunnerTaskMixin, JvmToolTaskMixin, JvmTask):
  """
  :API: public
  """

  @classmethod
  def register_options(cls, register):
    super(JUnitRun, cls).register_options(register)
    register('--batch-size', advanced=True, type=int, default=sys.maxint,
             help='Run at most this many tests in a single test process.')
    register('--test', type=list,
             help='Force running of just these tests.  Tests can be specified using any of: '
                  '[classname], [classname]#[methodname], [filename] or [filename]#[methodname]')
    register('--per-test-timer', type=bool, help='Show progress and timer for each test.')
    register('--default-concurrency', advanced=True,
             choices=JUnitTests.VALID_CONCURRENCY_OPTS, default=JUnitTests.CONCURRENCY_SERIAL,
             help='Set the default concurrency mode for running tests not annotated with'
                  ' @TestParallel or @TestSerial.')
    register('--parallel-threads', advanced=True, type=int, default=0,
             help='Number of threads to run tests in parallel. 0 for autoset.')
    register('--test-shard', advanced=True,
             help='Subset of tests to run, in the form M/N, 0 <= M < N. '
                  'For example, 1/3 means run tests number 2, 5, 8, 11, ...')
    register('--output-mode', choices=['ALL', 'FAILURE_ONLY', 'NONE'], default='NONE',
             help='Specify what part of output should be passed to stdout. '
                  'In case of FAILURE_ONLY and parallel tests execution '
                  'output can be partial or even wrong. '
                  'All tests output also redirected to files in .pants.d/test/junit.')
    register('--cwd', advanced=True,
             help='Set the working directory. If no argument is passed, use the build root. '
                  'If cwd is set on a target, it will supersede this argument.')
    register('--strict-jvm-version', type=bool, advanced=True,
             help='If true, will strictly require running junits with the same version of java as '
                  'the platform -target level. Otherwise, the platform -target level will be '
                  'treated as the minimum jvm to run.')
    register('--failure-summary', type=bool, default=True,
             help='If true, includes a summary of which test-cases failed at the end of a failed '
                  'junit run.')
    register('--allow-empty-sources', type=bool, advanced=True,
             help='Allows a junit_tests() target to be defined with no sources.  Otherwise,'
                  'such a target will raise an error during the test run.')
    register('--use-experimental-runner', type=bool, advanced=True,
             help='Use experimental junit-runner logic for more options for parallelism.')
    register('--html-report', type=bool,
             help='If true, generate an html summary report of tests that were run.')
    register('--open', type=bool,
             help='Attempt to open the html summary report in a browser (implies --html-report)')
    # TODO: Yuck, but will improve once coverage steps are in their own tasks.
    for c in [Coverage, Cobertura]:
      c.register_options(register, cls.register_jvm_tool)

  @classmethod
  def subsystem_dependencies(cls):
    return super(JUnitRun, cls).subsystem_dependencies() + (DistributionLocator, JUnit)

  @classmethod
  def request_classes_by_source(cls, test_specs):
    """Returns true if the given test specs require the `classes_by_source` product to satisfy."""
    buildroot = get_buildroot()
    for test_spec in test_specs:
      if isinstance(_TestSpecification.parse(buildroot, test_spec), _SourcefileSpec):
        return True
    return False

  @classmethod
  def prepare(cls, options, round_manager):
    super(JUnitRun, cls).prepare(options, round_manager)

    # Compilation and resource preparation must have completed.
    round_manager.require_data('runtime_classpath')

    # If the given test specs require the classes_by_source product, request it.
    if cls.request_classes_by_source(options.test or ()):
      round_manager.require_data('classes_by_source')

  def __init__(self, *args, **kwargs):
    super(JUnitRun, self).__init__(*args, **kwargs)

    options = self.get_options()
    self._tests_to_run = options.test
    self._batch_size = options.batch_size
    self._fail_fast = options.fail_fast
    self._working_dir = options.cwd or get_buildroot()
    self._strict_jvm_version = options.strict_jvm_version
    self._failure_summary = options.failure_summary
    self._open = options.open
    self._html_report = self._open or options.html_report

  @memoized_method
  def _args(self, output_dir):
    args = self.args[:]

    options = self.get_options()
    if options.output_mode == 'ALL':
      args.append('-output-mode=ALL')
    elif options.output_mode == 'FAILURE_ONLY':
      args.append('-output-mode=FAILURE_ONLY')
    else:
      args.append('-output-mode=NONE')

    if self._fail_fast:
      args.append('-fail-fast')
    args.append('-outdir')
    args.append(output_dir)
    if options.per_test_timer:
      args.append('-per-test-timer')

    if options.default_concurrency == JUnitTests.CONCURRENCY_PARALLEL_CLASSES_AND_METHODS:
      if not options.use_experimental_runner:
        self.context.log.warn('--default-concurrency=PARALLEL_CLASSES_AND_METHODS is '
                              'experimental, use --use-experimental-runner.')
      args.append('-default-concurrency')
      args.append('PARALLEL_CLASSES_AND_METHODS')
    elif options.default_concurrency == JUnitTests.CONCURRENCY_PARALLEL_METHODS:
      if not options.use_experimental_runner:
        self.context.log.warn('--default-concurrency=PARALLEL_METHODS is experimental, use '
                              '--use-experimental-runner.')
      if options.test_shard:
        # NB(zundel): The experimental junit runner doesn't support test sharding natively.  The
        # legacy junit runner allows both methods and classes to run in parallel with this option.
        self.context.log.warn('--default-concurrency=PARALLEL_METHODS with test sharding will '
                              'run classes in parallel too.')
      args.append('-default-concurrency')
      args.append('PARALLEL_METHODS')
    elif options.default_concurrency == JUnitTests.CONCURRENCY_PARALLEL_CLASSES:
      args.append('-default-concurrency')
      args.append('PARALLEL_CLASSES')
    elif options.default_concurrency == JUnitTests.CONCURRENCY_SERIAL:
      args.append('-default-concurrency')
      args.append('SERIAL')

    args.append('-parallel-threads')
    args.append(str(options.parallel_threads))

    if options.test_shard:
      args.append('-test-shard')
      args.append(options.test_shard)

    if options.use_experimental_runner:
      self.context.log.info('Using experimental junit-runner logic.')
      args.append('-use-experimental-runner')

    return args

  def classpath(self, targets, classpath_product=None, **kwargs):
    return super(JUnitRun, self).classpath(targets,
                                           classpath_product=classpath_product,
                                           include_scopes=Scopes.JVM_TEST_SCOPES,
                                           **kwargs)

  def preferred_jvm_distribution_for_targets(self, targets):
    return JvmPlatform.preferred_jvm_distribution([target.platform for target in targets
                                                  if isinstance(target, JvmTarget)],
                                                  self._strict_jvm_version)

  def _spawn(self, distribution, executor=None, *args, **kwargs):
    """Returns a processhandler to a process executing java.

    :param Executor executor: the java subprocess executor to use. If not specified, construct
      using the distribution.
    :param Distribution distribution: The JDK or JRE installed.
    :rtype: ProcessHandler
    """

    actual_executor = executor or SubprocessExecutor(distribution)
    return distribution.execute_java_async(*args,
                                           executor=actual_executor,
                                           **kwargs)

  def execute_java_for_targets(self, targets, *args, **kwargs):
    """Execute java for targets using the test mixin spawn and wait.

    Activates timeouts and other common functionality shared among tests.
    """

    distribution = self.preferred_jvm_distribution_for_targets(targets)
    actual_executor = kwargs.get('executor') or SubprocessExecutor(distribution)
    return self._spawn_and_wait(*args,
                                executor=actual_executor,
                                distribution=distribution,
                                **kwargs)

  def execute_java_for_coverage(self, targets, executor=None, *args, **kwargs):
    """Execute java for targets directly and don't use the test mixin.

    This execution won't be wrapped with timeouts and other testmixin code common
    across test targets. Used for coverage instrumentation.
    """

    distribution = self.preferred_jvm_distribution_for_targets(targets)
    actual_executor = executor or SubprocessExecutor(distribution)
    return distribution.execute_java(*args, executor=actual_executor, **kwargs)

  def _collect_test_targets(self, targets):
    """Return a test registry mapping the tests found in the given targets.

    If `self._tests_to_run` is set, return a registry of explicitly specified tests instead.

    :returns: A registry of tests to run.
    :rtype: :class:`pants.java.junit.junit_xml_parser.Test.RegistryOfTests`
    """

    test_registry = RegistryOfTests(tuple(self._calculate_tests_from_targets(targets)))

    if targets and self._tests_to_run:
      # If there are some junit_test targets in the graph, find ones that match the requested
      # test(s).
      possible_test_to_target = {}
      unknown_tests = []
      for possible_test in self._get_possible_tests_to_run():
        target = test_registry.get_owning_target(possible_test)
        if target is None:
          unknown_tests.append(possible_test)
        else:
          possible_test_to_target[possible_test] = target

      if len(unknown_tests) > 0:
        raise TaskError("No target found for test specifier(s):\n\n  '{}'\n\nPlease change "
                        "specifier or bring in the proper target(s)."
                        .format("'\n  '".join(t.render_test_spec() for t in unknown_tests)))

      return RegistryOfTests(possible_test_to_target)
    else:
      return test_registry

  def _run_tests(self, test_registry, output_dir, coverage=None):

    def parse_error_handler(parse_error):
      # Just log and move on since the result is only used to characterize failures, and raising
      # an error here would just distract from the underlying test failures.
      self.context.log.error('Error parsing test result file {path}: {cause}'
        .format(path=parse_error.xml_path, cause=parse_error.cause))

    if coverage:
      extra_jvm_options = coverage.extra_jvm_options
      classpath_prepend = coverage.classpath_prepend
      classpath_append = coverage.classpath_append
    else:
      extra_jvm_options = []
      classpath_prepend = ()
      classpath_append = ()

    tests_by_properties = test_registry.index(
        lambda tgt: tgt.cwd if tgt.cwd is not None else self._working_dir,
        lambda tgt: tgt.test_platform,
        lambda tgt: tgt.payload.extra_jvm_options,
        lambda tgt: tgt.payload.extra_env_vars,
        lambda tgt: tgt.concurrency,
        lambda tgt: tgt.threads)

    # the below will be None if not set, and we'll default back to runtime_classpath
    classpath_product = self.context.products.get_data('instrument_classpath')

    result = 0
    for properties, tests in tests_by_properties.items():
      (workdir, platform, target_jvm_options, target_env_vars, concurrency, threads) = properties
      for batch in self._partition(tests):
        # Batches of test classes will likely exist within the same targets: dedupe them.
        relevant_targets = {test_registry.get_owning_target(t) for t in batch}
        complete_classpath = OrderedSet()
        complete_classpath.update(classpath_prepend)
        complete_classpath.update(JUnit.global_instance().runner_classpath(self.context))
        complete_classpath.update(self.classpath(relevant_targets,
                                                 classpath_product=classpath_product))
        complete_classpath.update(classpath_append)
        distribution = JvmPlatform.preferred_jvm_distribution([platform], self._strict_jvm_version)

        # Override cmdline args with values from junit_test() target that specify concurrency:
        args = self._args(output_dir) + [u'-xmlreport']

        if concurrency is not None:
          args = remove_arg(args, '-default-parallel')
          if concurrency == JUnitTests.CONCURRENCY_SERIAL:
            args = ensure_arg(args, '-default-concurrency', param='SERIAL')
          elif concurrency == JUnitTests.CONCURRENCY_PARALLEL_CLASSES:
            args = ensure_arg(args, '-default-concurrency', param='PARALLEL_CLASSES')
          elif concurrency == JUnitTests.CONCURRENCY_PARALLEL_METHODS:
            args = ensure_arg(args, '-default-concurrency', param='PARALLEL_METHODS')
          elif concurrency == JUnitTests.CONCURRENCY_PARALLEL_CLASSES_AND_METHODS:
            args = ensure_arg(args, '-default-concurrency', param='PARALLEL_CLASSES_AND_METHODS')

        if threads is not None:
          args = remove_arg(args, '-parallel-threads', has_param=True)
          args += ['-parallel-threads', str(threads)]

        batch_test_specs = [test.render_test_spec() for test in batch]
        with argfile.safe_args(batch_test_specs, self.get_options()) as batch_tests:
          self.context.log.debug('CWD = {}'.format(workdir))
          self.context.log.debug('platform = {}'.format(platform))
          with environment_as(**dict(target_env_vars)):
            result += abs(self._spawn_and_wait(
              executor=SubprocessExecutor(distribution),
              distribution=distribution,
              classpath=complete_classpath,
              main=JUnit.RUNNER_MAIN,
              jvm_options=self.jvm_options + extra_jvm_options + list(target_jvm_options),
              args=args + batch_tests,
              workunit_factory=self.context.new_workunit,
              workunit_name='run',
              workunit_labels=[WorkUnitLabel.TEST],
              cwd=workdir,
              synthetic_jar_dir=output_dir,
              create_synthetic_jar=self.synthetic_classpath,
            ))

          tests_info = self.parse_test_info(output_dir, parse_error_handler, ['classname'])
          for test_name, test_info in tests_info.items():
            test_item = Test(test_info['classname'], test_name)
            test_target = test_registry.get_owning_target(test_item)
            for test_info_key, test_info_val in test_info.items():
              key_list = [test_name, test_info_key]
              self.report_test_info(self.options_scope, test_target, key_list, test_info_val)

          if result != 0 and self._fail_fast:
            break

    if result != 0:
      target_to_failed_test = parse_failed_targets(test_registry, output_dir, parse_error_handler)

      def sort_owning_target(t):
        return t.address.spec if t else None

      failed_targets = sorted(target_to_failed_test, key=sort_owning_target)
      error_message_lines = []
      if self._failure_summary:
        def render_owning_target(t):
          return t.address.spec if t else '<Unknown Target>'

        for target in failed_targets:
          error_message_lines.append('\n{indent}{owner}'.format(indent=' ' * 4,
                                                                owner=render_owning_target(target)))
          for test in sorted(target_to_failed_test[target]):
            error_message_lines.append('{indent}{classname}#{methodname}'
                                       .format(indent=' ' * 8,
                                               classname=test.classname,
                                               methodname=test.methodname))
      error_message_lines.append(
        '\njava {main} ... exited non-zero ({code}); {failed} failed {targets}.'
          .format(main=JUnit.RUNNER_MAIN, code=result, failed=len(failed_targets),
                  targets=pluralize(len(failed_targets), 'target'))
      )
      raise ErrorWhileTesting('\n'.join(error_message_lines), failed_targets=list(failed_targets))

  def _partition(self, tests):
    stride = min(self._batch_size, len(tests))
    for i in range(0, len(tests), stride):
      yield tests[i:i + stride]

  def _get_possible_tests_to_run(self):
    buildroot = get_buildroot()
    for test_spec in self._tests_to_run:
      for test in _TestSpecification.parse(buildroot, test_spec).iter_possible_tests(self.context):
        yield test

  def _calculate_tests_from_targets(self, targets):
    """
    :param list targets: list of targets to calculate test classes for.
    generates tuples (Test, Target).
    """
    classpath_products = self.context.products.get_data('runtime_classpath')
    for target in targets:
      contents = ClasspathUtil.classpath_contents((target,), classpath_products, confs=self.confs)
      for f in contents:
        classname = ClasspathUtil.classname_for_rel_classfile(f)
        if classname:
          yield Test(classname=classname), target

  def _test_target_filter(self):
    def target_filter(target):
      return isinstance(target, JUnitTests)
    return target_filter

  def _validate_target(self, target):
    # TODO: move this check to an optional phase in goal_runner, so
    # that missing sources can be detected early.
    if not target.payload.sources.source_paths and not self.get_options().allow_empty_sources:
      msg = 'JUnitTests target must include a non-empty set of sources.'
      raise TargetDefinitionException(target, msg)

  def _execute(self, all_targets):
    # NB: We only run tests within junit_tests targets, but if coverage options are
    # specified, we want to instrument and report on all the original targets, not
    # just the test targets.

    test_registry = self._collect_test_targets(self._get_test_targets())
    if test_registry.empty:
      return

    with self._isolation(all_targets) as (output_dir, do_report, coverage):
      try:
        self._run_tests(test_registry, output_dir, coverage)
        do_report(exc=None)
      except TaskError as e:
        do_report(exc=e)
        raise

  @contextmanager
  def _isolation(self, all_targets):
    run_dir = '_runs'
    output_dir = os.path.join(self.workdir, run_dir, Target.identify(all_targets))
    safe_mkdir(output_dir, clean=True)

    coverage = None
    options = self.get_options()
    if options.coverage or options.is_flagged('coverage_open'):
      coverage_processor = options.coverage_processor
      if coverage_processor == 'cobertura':
        settings = CoberturaTaskSettings.from_task(self, workdir=output_dir)
        coverage = Cobertura(settings)
      else:
        raise TaskError('unknown coverage processor {0}'.format(coverage_processor))

    self.context.release_lock()
    if coverage:
      coverage.instrument(targets=all_targets,
                          compute_junit_classpath=lambda: self.classpath(all_targets),
                          execute_java_for_targets=self.execute_java_for_coverage)

    def do_report(exc=None):
      if coverage:
        coverage.report(all_targets, self.execute_java_for_coverage, tests_failed_exception=exc)
      if self._html_report:
        html_file_path = JUnitHtmlReport().report(output_dir, os.path.join(output_dir, 'reports'))
        if self._open:
          desktop.ui_open(html_file_path)

    try:
      yield output_dir, do_report, coverage
    finally:
      # NB: Deposit of the "current" test output in the root workdir (.pants.d/test/junit) is a
      # defacto public API and so we implement that behavior here to maintain backwards
      # compatibility for non-pants report file consumers.
      # TODO(John Sirois): Deprecate this ~API and provide a stable directory solution for test
      # output: https://github.com/pantsbuild/pants/issues/3879
      lock_file = '.file_lock'
      with OwnerPrintingInterProcessFileLock(os.path.join(self.workdir, lock_file)):
        # Kill everything except the isolated runs/ dir.
        for name in os.listdir(self.workdir):
          path = os.path.join(self.workdir, name)
          if name not in (run_dir, lock_file):
            if os.path.isdir(path):
              safe_rmtree(path)
            else:
              os.unlink(path)

        # Link all the isolated run/ dir contents back up to the stable workdir
        for name in os.listdir(output_dir):
          path = os.path.join(output_dir, name)
          os.symlink(path, os.path.join(self.workdir, name))
