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
from pants.build_graph.target_scopes import Scopes
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.task.testrunner_task_mixin import TestRunnerTaskMixin
from pants.util import desktop
from pants.util.argutil import ensure_arg, remove_arg
from pants.util.contextutil import environment_as
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
        settings = CoberturaTaskSettings.from_task(self)
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
    self._open = options.open
    self._html_report = self._open or options.html_report

    if options.output_mode == 'ALL':
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
      # TODO(zundel): Remove when --default_parallel finishes deprecation
      if options.default_concurrency != junit_tests.CONCURRENCY_SERIAL:
        self.context.log.warn('--default-parallel overrides --default-concurrency')
      self._args.append('-default-concurrency')
      self._args.append('PARALLEL_CLASSES')
    else:
      if options.default_concurrency == junit_tests.CONCURRENCY_PARALLEL_CLASSES_AND_METHODS:
        if not options.use_experimental_runner:
          self.context.log.warn(
            '--default-concurrency=PARALLEL_CLASSES_AND_METHODS is experimental, use --use-experimental-runner.')
        self._args.append('-default-concurrency')
        self._args.append('PARALLEL_CLASSES_AND_METHODS')
      elif options.default_concurrency == junit_tests.CONCURRENCY_PARALLEL_METHODS:
        if not options.use_experimental_runner:
          self.context.log.warn(
            '--default-concurrency=PARALLEL_METHODS is experimental, use --use-experimental-runner.')
        if options.test_shard:
          # NB(zundel): The experimental junit runner doesn't support test sharding natively.  The
          # legacy junit runner allows both methods and classes to run in parallel with this option.
          self.context.log.warn(
            '--default-concurrency=PARALLEL_METHODS with test sharding will run classes in parallel too.')
        self._args.append('-default-concurrency')
        self._args.append('PARALLEL_METHODS')
      elif options.default_concurrency == junit_tests.CONCURRENCY_PARALLEL_CLASSES:
        self._args.append('-default-concurrency')
        self._args.append('PARALLEL_CLASSES')
      elif options.default_concurrency == junit_tests.CONCURRENCY_SERIAL:
        self._args.append('-default-concurrency')
        self._args.append('SERIAL')

    self._args.append('-parallel-threads')
    self._args.append(str(options.parallel_threads))

    if options.test_shard:
      self._args.append('-test-shard')
      self._args.append(options.test_shard)

    if options.use_experimental_runner:
      self.context.log.info('Using experimental junit-runner logic.')
      self._args.append('-use-experimental-runner')

  def classpath(self, targets, classpath_product=None):
    return super(JUnitRun, self).classpath(targets, classpath_product=classpath_product,
                                           include_scopes=Scopes.JVM_TEST_SCOPES)

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
    return self._spawn_and_wait(*args, executor=actual_executor, distribution=distribution, **kwargs)

  def execute_java_for_coverage(self, targets, executor=None, *args, **kwargs):
    """Execute java for targets directly and don't use the test mixin.

    This execution won't be wrapped with timeouts and other testmixin code common
    across test targets. Used for coverage instrumentation.
    """

    distribution = self.preferred_jvm_distribution_for_targets(targets)
    actual_executor = executor or SubprocessExecutor(distribution)
    return distribution.execute_java(*args, executor=actual_executor, **kwargs)

  def _collect_test_targets(self, targets):
    """Returns a mapping from test names to target objects for all tests that are included in targets.

    If self._tests_to_run is set, return {test: None} for these tests instead.
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

    def get_test_filename(test_class_name):
      return os.path.join(self.workdir, 'TEST-{0}.xml'.format(test_class_name.replace('$', '-')))

    xml_filenames_to_targets = defaultdict()
    for test, target in tests_and_targets.items():
      if target is None:
        self.context.log.warn('Unknown target for test %{0}'.format(test))

      # Look for a TEST-*.xml file that matches the classname or a containing classname
      test_class_name = test
      for _part in test.split('$'):
        filename = get_test_filename(test_class_name)
        if os.path.exists(filename):
          xml_filenames_to_targets[filename] = target
          break
        else:
          test_class_name = test_class_name.rsplit('$', 1)[0]

    failed_targets = defaultdict(set)
    for xml_filename, target in xml_filenames_to_targets.items():
      try:
        xml = XmlParser.from_file(xml_filename)
        failures = int(xml.get_attribute('testsuite', 'failures'))
        errors = int(xml.get_attribute('testsuite', 'errors'))

        if target and (failures or errors):
          for testcase in xml.parsed.getElementsByTagName('testcase'):
            test_failed = testcase.getElementsByTagName('failure')
            test_errored = testcase.getElementsByTagName('error')
            if test_failed or test_errored:
              failed_targets[target].add('{testclass}#{testname}'.format(
                  testclass=testcase.getAttribute('classname'),
                  testname=testcase.getAttribute('name'),
              ))
      except (XmlParser.XmlError, ValueError) as e:
        self.context.log.error('Error parsing test result file {0}: {1}'.format(xml_filename, e))

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

    tests_by_properties = self._tests_by_properties(
      tests_to_targets,
      self._infer_workdir,
      lambda target: target.test_platform,
      lambda target: target.payload.extra_jvm_options,
      lambda target: target.payload.extra_env_vars,
      lambda target: target.concurrency,
      lambda target: target.threads
    )

    # the below will be None if not set, and we'll default back to runtime_classpath
    classpath_product = self.context.products.get_data('instrument_classpath')

    result = 0
    for properties, tests in tests_by_properties.items():
      (workdir, platform, target_jvm_options, target_env_vars, concurrency, threads) = properties
      for batch in self._partition(tests):
        # Batches of test classes will likely exist within the same targets: dedupe them.
        relevant_targets = set(map(tests_to_targets.get, batch))
        complete_classpath = OrderedSet()
        complete_classpath.update(classpath_prepend)
        complete_classpath.update(self.tool_classpath('junit'))
        complete_classpath.update(self.classpath(relevant_targets,
                                                 classpath_product=classpath_product))
        complete_classpath.update(classpath_append)
        distribution = JvmPlatform.preferred_jvm_distribution([platform], self._strict_jvm_version)

        # Override cmdline args with values from junit_test() target that specify concurrency:
        args = self._args + [u'-xmlreport']

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
              args=args + batch_tests,
              workunit_factory=self.context.new_workunit,
              workunit_name='run',
              workunit_labels=[WorkUnitLabel.TEST],
              cwd=workdir,
              synthetic_jar_dir=self.workdir,
              create_synthetic_jar=self.synthetic_classpath,
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

  def _execute(self, targets):
    """Implements the primary junit test execution.

    This method is called by the TestRunnerTaskMixin, which contains the primary Task.execute function
    and wraps this method in timeouts.
    """

    # We only run tests within java_tests/junit_tests targets.
    #
    # But if coverage options are specified, we want to instrument
    # and report on all the original targets, not just the test targets.
    #
    # We've already filtered out the non-test targets in the
    # TestRunnerTaskMixin, so the mixin passes to us both the test
    # targets and the unfiltered list of targets
    tests_and_targets = self._collect_test_targets(self._get_test_targets())

    if not tests_and_targets:
      return

    def compute_complete_classpath():
      return self.classpath(targets)

    self.context.release_lock()
    if self._coverage:
      self._coverage.instrument(
        targets, tests_and_targets.keys(), compute_complete_classpath, self.execute_java_for_coverage)

    def _do_report(exception=None):
      if self._coverage:
        self._coverage.report(
          targets, tests_and_targets.keys(), self.execute_java_for_coverage, tests_failed_exception=exception)
      if self._html_report:
        html_file_path = JUnitHtmlReport().report(self.workdir, os.path.join(self.workdir, 'reports'))
        if self._open:
          desktop.ui_open(html_file_path)

    try:
      self._run_tests(tests_and_targets)
      _do_report(exception=None)
    except TaskError as e:
      _do_report(exception=e)
      raise
