# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import shutil
import sys
from collections import defaultdict
from contextlib import contextmanager

from six.moves import range
from twitter.common.collections import OrderedSet

from pants.backend.jvm import argfile
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.java_tests import JavaTests as junit_tests
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.coverage.base import Coverage
from pants.backend.jvm.tasks.coverage.cobertura import Cobertura, CoberturaTaskSettings
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.reports.junit_html_report import JUnitHtmlReport
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException, TaskError, TestFailedTaskError
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.target import Target
from pants.build_graph.target_scopes import Scopes
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.process.lock import OwnerPrintingInterProcessFileLock
from pants.task.testrunner_task_mixin import TestRunnerTaskMixin
from pants.util import desktop
from pants.util.argutil import ensure_arg, remove_arg
from pants.util.contextutil import environment_as
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_method
from pants.util.objects import datatype
from pants.util.strutil import pluralize
from pants.util.xml_parser import XmlParser


def _interpret_test_spec(test_spec):
  """Parses a test spec string.

  Returns either a (sourcefile,method) on the left, or a (classname,method) on the right.
  """
  components = test_spec.split('#', 2)
  classname_or_srcfile = components[0]
  methodname = components[1] if len(components) == 2 else None

  if os.path.exists(classname_or_srcfile):
    # It's a source file.
    return (classname_or_srcfile, methodname), None
  else:
    # It's a classname.
    return None, (classname_or_srcfile, methodname)


class _Test(datatype('Test', ['classname', 'name'])):
  """Describes a junit-style test."""

  def __new__(cls, classname, name=None):
    # We deliberately normalize an empty name ('') to None.
    return super(_Test, cls).__new__(cls, classname, name or None)

  def enclosing(self):
    """Return the test enclosing this test.

    :returns: This test's enclosing test or else this test if there is no enclosing test.
    :rtype: :class:`_Test`
    """
    return self if self.name is None else _Test(self.classname)

  def render(self):
    """Renders this test in `classname#methodname` format.

    :returns: A rendering of this test in the semi-standard test specification format.
    :rtype: string
    """
    return self.classname if self.name is None else '{}#{}'.format(self.classname, self.name)


class _TestRegistry(object):
  """A registry of tests and the targets that own them."""

  def __init__(self, test_to_target):
    self._test_to_target = test_to_target

  @property
  def empty(self):
    """Return true if there ar no registered tests.

    :returns: `True` if this registry is empty.
    :rtype: bool
    """
    return len(self._test_to_target) == 0

  def get_target(self, test):
    """Return the target that owns the given test.

    :param test: The test to find an owning target for.
    :type test: :class:`_Test`
    :returns: The target that owns the given `test` or else `None` if the owning target is unknown.
    :rtype: :class:`pants.build_graph.target.Target`
    """
    target = self._test_to_target.get(test)
    if target is None:
      target = self._test_to_target.get(test.enclosing())
    return target

  def index(self, *indexers):
    """Indexes the tests in this registry by sets of common properties their owning targets share.

    :param indexers: Functions that index a target, producing a hashable key for a given property.
    :return: An index of tests by shared properties.
    :rtype: dict from tuple of properties to a tuple of :class:`Test`.
    """
    def combined_indexer(tgt):
      return tuple(indexer(tgt) for indexer in indexers)

    properties = defaultdict(OrderedSet)
    for test, target in self._test_to_target.items():
      properties[combined_indexer(target)].add(test)
    return {prop: tuple(tests) for prop, tests in properties.items()}


class JUnitRun(TestRunnerTaskMixin, JvmToolTaskMixin, JvmTask):
  """
  :API: public
  """

  _MAIN = 'org.pantsbuild.tools.junit.ConsoleRunner'

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
             choices=junit_tests.VALID_CONCURRENCY_OPTS, default=junit_tests.CONCURRENCY_SERIAL,
             help='Set the default concurrency mode for running tests not annotated with'
                  ' @TestParallel or @TestSerial.')
    register('--default-parallel', advanced=True, type=bool,
             removal_hint='Use --default-concurrency instead.', removal_version='1.3.0',
             help='Run classes without @TestParallel or @TestSerial annotations in parallel.')
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
    cls.register_jvm_tool(register,
                          'junit',
                          classpath=[
                            JarDependency(org='org.pantsbuild', name='junit-runner', rev='1.0.13'),
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
                            Shader.exclude_package('org.pantsbuild.junit.annotations',
                                                   recursive=True),
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
      src_spec, _ = _interpret_test_spec(test_spec)
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

    if options.default_parallel:
      # TODO(zundel): Remove when --default_parallel finishes deprecation
      if options.default_concurrency != junit_tests.CONCURRENCY_SERIAL:
        self.context.log.warn('--default-parallel overrides --default-concurrency')
      args.append('-default-concurrency')
      args.append('PARALLEL_CLASSES')
    else:
      if options.default_concurrency == junit_tests.CONCURRENCY_PARALLEL_CLASSES_AND_METHODS:
        if not options.use_experimental_runner:
          self.context.log.warn('--default-concurrency=PARALLEL_CLASSES_AND_METHODS is '
                                'experimental, use --use-experimental-runner.')
        args.append('-default-concurrency')
        args.append('PARALLEL_CLASSES_AND_METHODS')
      elif options.default_concurrency == junit_tests.CONCURRENCY_PARALLEL_METHODS:
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
      elif options.default_concurrency == junit_tests.CONCURRENCY_PARALLEL_CLASSES:
        args.append('-default-concurrency')
        args.append('PARALLEL_CLASSES')
      elif options.default_concurrency == junit_tests.CONCURRENCY_SERIAL:
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
    :rtype: :class:`_TestRegistry`
    """

    test_registry = _TestRegistry(dict(list(self._calculate_tests_from_targets(targets))))

    if targets and self._tests_to_run:
      # If there are some junit_test targets in the graph, find ones that match the requested
      # test(s).
      test_to_target = {}
      unknown_tests = []
      for test in self._get_tests_to_run():
        # A test might contain #specific_method, which is not needed to find a target.
        target = test_registry.get_target(test)
        if target is None:
          unknown_tests.append(test)
        else:
          test_to_target[test] = target

      if len(unknown_tests) > 0:
        raise TaskError("No target found for test specifier(s):\n\n  '{}'\n\nPlease change "
                        "specifier or bring in the proper target(s)."
                        .format("'\n  '".join(t.render() for t in unknown_tests)))

      return _TestRegistry(test_to_target)
    else:
      return test_registry

  _JUNIT_XML_MATCHER = re.compile(r'^TEST-.+\.xml$')

  def _get_failed_targets(self, test_registry, output_dir):
    """Return a mapping of target -> set of individual test cases that failed.

    Targets with no failed tests are omitted.

    Analyzes JUnit XML files to figure out which test had failed.

    The individual test cases are formatted strings of the form org.foo.bar.classname#methodName.

    :tests_and_targets: {test: target} mapping.
    """
    failed_targets = defaultdict(set)
    for path in os.listdir(output_dir):
      if self._JUNIT_XML_MATCHER.match(path):
        try:
          xml = XmlParser.from_file(os.path.join(output_dir, path))
          failures = int(xml.get_attribute('testsuite', 'failures'))
          errors = int(xml.get_attribute('testsuite', 'errors'))
          if failures or errors:
            for testcase in xml.parsed.getElementsByTagName('testcase'):
              test_failed = testcase.getElementsByTagName('failure')
              test_errored = testcase.getElementsByTagName('error')
              if test_failed or test_errored:
                test = _Test(testcase.getAttribute('classname'), testcase.getAttribute('name'))
                target = test_registry.get_target(test)
                failed_targets[target].add(test)
        except (XmlParser.XmlError, ValueError) as e:
          self.context.log.error('Error parsing test result file {0}: {1}'.format(path, e))

    return dict(failed_targets)

  def _run_tests(self, test_registry, output_dir, coverage=None):
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
        relevant_targets = {test_registry.get_target(t) for t in batch}
        complete_classpath = OrderedSet()
        complete_classpath.update(classpath_prepend)
        complete_classpath.update(self.tool_classpath('junit'))
        complete_classpath.update(self.classpath(relevant_targets,
                                                 classpath_product=classpath_product))
        complete_classpath.update(classpath_append)
        distribution = JvmPlatform.preferred_jvm_distribution([platform], self._strict_jvm_version)

        # Override cmdline args with values from junit_test() target that specify concurrency:
        args = self._args(output_dir) + [u'-xmlreport']

        if concurrency is not None:
          args = remove_arg(args, '-default-parallel')
          if concurrency == junit_tests.CONCURRENCY_SERIAL:
            args = ensure_arg(args, '-default-concurrency', param='SERIAL')
          elif concurrency == junit_tests.CONCURRENCY_PARALLEL_CLASSES:
            args = ensure_arg(args, '-default-concurrency', param='PARALLEL_CLASSES')
          elif concurrency == junit_tests.CONCURRENCY_PARALLEL_METHODS:
            args = ensure_arg(args, '-default-concurrency', param='PARALLEL_METHODS')
          elif concurrency == junit_tests.CONCURRENCY_PARALLEL_CLASSES_AND_METHODS:
            args = ensure_arg(args, '-default-concurrency', param='PARALLEL_CLASSES_AND_METHODS')

        if threads is not None:
          args = remove_arg(args, '-parallel-threads', has_param=True)
          args += ['-parallel-threads', str(threads)]

        with argfile.safe_args(batch, self.get_options()) as batch_tests:
          self.context.log.debug('CWD = {}'.format(workdir))
          self.context.log.debug('platform = {}'.format(platform))
          with environment_as(**dict(target_env_vars)):
            result += abs(self._spawn_and_wait(
              executor=SubprocessExecutor(distribution),
              distribution=distribution,
              classpath=complete_classpath,
              main=JUnitRun._MAIN,
              jvm_options=self.jvm_options + extra_jvm_options + list(target_jvm_options),
              args=args + [test.render() for test in batch_tests],
              workunit_factory=self.context.new_workunit,
              workunit_name='run',
              workunit_labels=[WorkUnitLabel.TEST],
              cwd=workdir,
              synthetic_jar_dir=output_dir,
              create_synthetic_jar=self.synthetic_classpath,
            ))

          if result != 0 and self._fail_fast:
            break

    if result != 0:
      target_to_failed_test = self._get_failed_targets(test_registry, output_dir)
      failed_targets = sorted(target_to_failed_test, key=lambda target: target.address.spec)
      error_message_lines = []
      if self._failure_summary:
        for target in failed_targets:
          error_message_lines.append('\n{indent}{address}'.format(indent=' ' * 4,
                                                                  address=target.address.spec))
          for test in sorted(target_to_failed_test[target]):
            error_message_lines.append('{indent}{classname}#{name}'.format(indent=' ' * 8,
                                                                           classname=test.classname,
                                                                           name=test.name))
      error_message_lines.append(
        '\njava {main} ... exited non-zero ({code}); {failed} failed {targets}.'
          .format(main=JUnitRun._MAIN, code=result, failed=len(failed_targets),
                  targets=pluralize(len(failed_targets), 'target'))
      )
      raise TestFailedTaskError('\n'.join(error_message_lines), failed_targets=list(failed_targets))

  def _partition(self, tests):
    stride = min(self._batch_size, len(tests))
    for i in range(0, len(tests), stride):
      yield tests[i:i + stride]

  def _get_tests_to_run(self):
    for test_spec in self._tests_to_run:
      src_spec, cls_spec = _interpret_test_spec(test_spec)
      if src_spec:
        sourcefile, methodname = src_spec
        for classname in self._classnames_from_source_file(sourcefile):
          # Tack the methodname onto all classes in the source file, as we
          # can't know which method the user intended.
          yield _Test(classname, methodname)
      else:
        classname, methodname = cls_spec
        yield _Test(classname, methodname)

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
          yield _Test(classname), target

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
          yield ClasspathUtil.classname_for_rel_classfile(cls)

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

  def _execute(self, all_targets):
    # NB: We only run tests within java_tests/junit_tests targets, but if coverage options are
    # specified, we want to instrument and report on all the original targets, not just the test
    # targets.

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
      lock_file = '.file_lock'
      with OwnerPrintingInterProcessFileLock(os.path.join(self.workdir, lock_file)):
        # Kill everything except the isolated runs/ dir.
        for name in os.listdir(self.workdir):
          path = os.path.join(self.workdir, name)
          if name not in (run_dir, lock_file):
            if os.path.isdir(path):
              shutil.rmtree(path)
            else:
              os.unlink(path)

        # Link all the isolated run/ dir contents back up to the stable workdir
        for name in os.listdir(output_dir):
          path = os.path.join(output_dir, name)
          os.symlink(path, os.path.join(self.workdir, name))
