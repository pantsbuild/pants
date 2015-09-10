# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import fnmatch
import os
import sys
from abc import abstractmethod
from collections import defaultdict, namedtuple

from six.moves import range
from twitter.common.collections import OrderedSet

from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.java_tests import JavaTests as junit_tests
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException, TaskError, TestFailedTaskError
from pants.base.revision import Revision
from pants.base.workunit import WorkUnitLabel
from pants.binaries import binary_util
from pants.java.distribution.distribution import DistributionLocator
from pants.util.contextutil import temporary_file_path
from pants.util.dirutil import (relativize_paths, safe_delete, safe_mkdir, safe_open, safe_rmtree,
                                touch)
from pants.util.strutil import safe_shlex_split
from pants.util.xml_parser import XmlParser


# TODO(ji): Add unit tests.

# The helper classes (_JUnitRunner and its subclasses) need to use
# methods inherited by JUnitRun from Task. Rather than pass a reference
# to the entire Task instance, we isolate the methods that are used
# in a named tuple and pass that one around.

# TODO(benjy): Why? This seems unnecessarily clunky. The runners only exist because we can't
# (yet?) pick a Task type based on cmd-line flags. But they act "as-if" they were Task types,
# so it seems prefectly reasonable for them to have a reference to the task.
# This trick just makes debugging harder, and requires extra work when a runner implementation
# needs some new thing from the task.
# TODO(ji): (responding to benjy's) IIRC, I was carrying the reference to the Task in very early
# versions, and jsirois suggested that I switch to the current form.
_TaskExports = namedtuple('_TaskExports',
                          ['classpath',
                           'task_options',
                           'jvm_options',
                           'args',
                           'confs',
                           'register_jvm_tool',
                           'tool_classpath',
                           'workdir'])


def _classfile_to_classname(cls):
  clsname, _ = os.path.splitext(cls.replace('/', '.'))
  return clsname


class _JUnitRunner(object):
  """Helper class to run JUnit tests with or without coverage.

  The default behavior is to just run JUnit tests."""

  @classmethod
  def register_options(cls, register, register_jvm_tool):
    register('--skip', action='store_true', help='Skip running junit.')
    register('--fail-fast', action='store_true',
             help='Fail fast on the first test failure in a suite.')
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
             help='Redirect test output to files in .pants.d/test/junit.')
    register('--cwd', advanced=True,
             help='Set the working directory. If no argument is passed, use the build root. '
                  'If cwd is set on a target, it will supersede this argument.')
    register('--strict-jvm-version', action='store_true', default=False, advanced=True,
             help='If true, will strictly require running junits with the same version of java as '
                  'the platform -target level. Otherwise, the platform -target level will be '
                  'treated as the minimum jvm to run.')
    register_jvm_tool(register,
                      'junit',
                      classpath=[
                        JarDependency(org='org.pantsbuild', name='junit-runner', rev='0.0.8'),
                      ],
                      main=JUnitRun._MAIN,
                      # TODO(John Sirois): Investigate how much less we can get away with.
                      # Clearly both tests and the runner need access to the same @Test, @Before,
                      # as well as other annotations, but there is also the Assert class and some
                      # subset of the @Rules, @Theories and @RunWith APIs.
                      custom_rules=[
                        Shader.exclude_package('org.junit', recursive=True),
                        Shader.exclude_package('org.hamcrest', recursive=True)
                      ])

  def __init__(self, task_exports, context):
    self._task_exports = task_exports
    self._context = context
    options = task_exports.task_options
    self._tests_to_run = options.test
    self._batch_size = options.batch_size
    self._fail_fast = options.fail_fast
    self._working_dir = options.cwd or get_buildroot()
    self._strict_jvm_version = options.strict_jvm_version
    self._args = copy.copy(task_exports.args)
    if options.suppress_output:
      self._args.append('-suppress-output')
    if self._fail_fast:
      self._args.append('-fail-fast')
    self._args.append('-outdir')
    self._args.append(task_exports.workdir)

    if options.per_test_timer:
      self._args.append('-per-test-timer')
    if options.default_parallel:
      self._args.append('-default-parallel')
    self._args.append('-parallel-threads')
    self._args.append(str(options.parallel_threads))

    if options.test_shard:
      self._args.append('-test-shard')
      self._args.append(options.test_shard)

  def execute(self, targets):
    # We only run tests within java_tests/junit_tests targets.
    #
    # But if coverage options are specified, we want to instrument
    # and report on all the original targets, not just the test targets.
    #
    # Thus, we filter out the non-java-tests targets first but
    # keep the original targets set intact for coverages.
    tests_and_targets = self._collect_test_targets(targets)

    if not tests_and_targets:
      return

    bootstrapped_cp = self._task_exports.tool_classpath('junit')

    def compute_complete_classpath():
      return self._task_exports.classpath(targets, cp=bootstrapped_cp)

    self._context.release_lock()
    self.instrument(targets, tests_and_targets.keys(), compute_complete_classpath)

    def _do_report(exception=None):
      self.report(targets, tests_and_targets.keys(), tests_failed_exception=exception)
    try:
      self.run(tests_and_targets)
      _do_report(exception=None)
    except TaskError as e:
      _do_report(exception=e)
      raise

  def instrument(self, targets, tests, compute_junit_classpath):
    """Called from coverage classes. Run any code instrumentation needed.

    Subclasses should override this if they need more work done.

    :param targets: an iterable that contains the targets to run tests for.
    :param tests: an iterable that contains all the test class names
      extracted from the testing targets.
    :param compute_junit_classpath: a function to compute a complete classpath for the context.
    """
    pass

  def run(self, tests_and_targets):
    """Run the tests in the appropriate environment.

    Subclasses should override this if they need more work done.

    :param tests_and_targets: a dict that contains all the test class names
      mapped to their targets extracted from the testing targets.
    """

    self._run_tests(tests_and_targets, JUnitRun._MAIN)

  def report(self, targets, tests, tests_failed_exception):
    """Post-processing of any test output.

    Subclasses should override this if they need anything done here.

    :param targets: an iterable that contains the targets to run tests for.
    :param tests: an iterable that contains all the test class names
      extracted from the testing targets.
    :param tests_failed_exception: if the run() method throws an exception,
      pass that exception here. It is used to determine whether any partial
      coverage should happen, if at all.
    """
    pass

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

  def _collect_test_targets(self, targets):
    """Returns a mapping from test names to target objects for all tests that
    are included in targets. If self._tests_to_run is set, return {test: None}
    for these tests instead.
    """

    java_tests_targets = list(self._test_target_candidates(targets))
    tests_from_targets = dict(list(self._calculate_tests_from_targets(java_tests_targets)))

    if java_tests_targets and self._tests_to_run:
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
    """Return a list of failed targets.

    Analyzes JUnit XML files to figure out which test had failed.

    :tests_and_targets: {test: target} mapping.
    """

    def get_test_filename(test):
      return os.path.join(self._task_exports.workdir, 'TEST-{0}.xml'.format(test))

    failed_targets = []

    for test, target in tests_and_targets.items():
      if target is None:
        self._context.log.warn('Unknown target for test %{0}'.format(test))

      filename = get_test_filename(test)

      if os.path.exists(filename):
        try:
          xml = XmlParser.from_file(filename)
          str_failures = xml.get_attribute('testsuite', 'failures')
          int_failures = int(str_failures)

          str_errors = xml.get_attribute('testsuite', 'errors')
          int_errors = int(str_errors)

          if target and (int_failures or int_errors):
            failed_targets.append(target)
        except (XmlParser.XmlError, ValueError) as e:
          self._context.log.error('Error parsing test result file {0}: {1}'.format(filename, e))

    return failed_targets

  def _run_tests(self, tests_to_targets, main, extra_jvm_options=None, classpath_prepend=(),
                 classpath_append=()):
    extra_jvm_options = extra_jvm_options or []

    tests_by_properties = self._tests_by_properties(tests_to_targets,
                                                    self._infer_workdir,
                                                    lambda target: target.test_platform)

    result = 0
    for (workdir, platform), tests in tests_by_properties.items():
      for batch in self._partition(tests):
        # Batches of test classes will likely exist within the same targets: dedupe them.
        relevant_targets = set(map(tests_to_targets.get, batch))
        classpath = self._task_exports.classpath(relevant_targets,
                                                 cp=self._task_exports.tool_classpath('junit'))
        complete_classpath = OrderedSet()
        complete_classpath.update(classpath_prepend)
        complete_classpath.update(classpath)
        complete_classpath.update(classpath_append)
        distribution = self.preferred_jvm_distribution([platform])
        with binary_util.safe_args(batch, self._task_exports.task_options) as batch_tests:
          self._context.log.debug('CWD = {}'.format(workdir))
          self._context.log.debug('platform = {}'.format(platform))
          result += abs(distribution.execute_java(
            classpath=complete_classpath,
            main=main,
            jvm_options=self._task_exports.jvm_options + extra_jvm_options,
            args=self._args + batch_tests + [u'-xmlreport'],
            workunit_factory=self._context.new_workunit,
            workunit_name='run',
            workunit_labels=[WorkUnitLabel.TEST],
            cwd=workdir,
          ))

          if result != 0 and self._fail_fast:
            break

    if result != 0:
      failed_targets = self._get_failed_targets(tests_to_targets)
      raise TestFailedTaskError(
        'java {0} ... exited non-zero ({1}); {2} failed targets.'
        .format(main, result, len(failed_targets)),
        failed_targets=failed_targets
      )

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
      for c in self._interpret_test_spec(test_spec):
        yield c

  def _test_target_candidates(self, targets):
    for target in targets:
      if isinstance(target, junit_tests):
        yield target

  def _calculate_tests_from_targets(self, targets):
    """
    :param list targets: list of targets to calculate test classes for.
    generates tuples (class_name, target).
    """
    targets_to_classes = self._context.products.get_data('classes_by_target')
    for target in self._test_target_candidates(targets):
      target_products = targets_to_classes.get(target)
      if target_products:
        for _, classes in target_products.rel_paths():
          for cls in classes:
            yield (_classfile_to_classname(cls), target)

  def _classnames_from_source_file(self, srcfile):
    relsrc = os.path.relpath(srcfile, get_buildroot())
    source_products = self._context.products.get_data('classes_by_source').get(relsrc)
    if not source_products:
      # It's valid - if questionable - to have a source file with no classes when, for
      # example, the source file has all its code commented out.
      self._context.log.warn('Source file {0} generated no classes'.format(srcfile))
    else:
      for _, classes in source_products.rel_paths():
        for cls in classes:
          yield _classfile_to_classname(cls)

  def _interpret_test_spec(self, test_spec):
    components = test_spec.split('#', 2)
    classname_or_srcfile = components[0]
    methodname = '#' + components[1] if len(components) == 2 else ''

    if os.path.exists(classname_or_srcfile):  # It's a source file.
      srcfile = classname_or_srcfile  # Alias for clarity.
      for cls in self._classnames_from_source_file(srcfile):
        # Tack the methodname onto all classes in the source file, as we
        # can't know which method the user intended.
        yield cls + methodname
    else:  # It's a classname.
      classname = classname_or_srcfile
      yield classname + methodname


#TODO(jtrobec): move code coverage into tasks, and out of the general UT code.
class _Coverage(_JUnitRunner):
  """Base class for emma-like coverage processors. Do not instantiate."""

  @classmethod
  def register_options(cls, register, register_jvm_tool):
    register('--coverage-patterns', advanced=True, action='append',
             help='Restrict coverage measurement. Values are class name prefixes in dotted form '
                  'with ? and * wildcards. If preceded with a - the pattern is excluded. For '
                  'example, to include all code in org.pantsbuild.raven except claws and the eye '
                  'you would use: {flag}=org.pantsbuild.raven.* {flag}=-org.pantsbuild.raven.claw '
                  '{flag}=-org.pantsbuild.raven.Eye.'.format(flag='--coverage_patterns'))
    register('--coverage-jvm-options', advanced=True, action='append',
             help='JVM flags to be added when running the coverage processor. For example: '
                  '{flag}=-Xmx4g {flag}=-XX:MaxPermSize=1g'.format(flag='--coverage-jvm-options'))
    register('--coverage-open', action='store_true',
             help='Open the generated HTML coverage report in a browser. Implies --coverage.')
    register('--coverage-force', advanced=True, action='store_true',
             help='Attempt to run the reporting phase of coverage even if tests failed '
                  '(defaults to False, as otherwise the coverage results would be unreliable).')

  def __init__(self, task_exports, context):
    super(_Coverage, self).__init__(task_exports, context)
    options = task_exports.task_options
    self._coverage = options.coverage
    self._coverage_filters = options.coverage_patterns or []

    self._coverage_jvm_options = []
    for jvm_option in options.coverage_jvm_options:
      self._coverage_jvm_options.extend(safe_shlex_split(jvm_option))

    self._coverage_dir = os.path.join(task_exports.workdir, 'coverage')
    self._coverage_instrument_dir = os.path.join(self._coverage_dir, 'classes')
    # TODO(ji): These may need to be transferred down to the Emma class, as the suffixes
    # may be emma-specific. Resolve when we also provide cobertura support.
    self._coverage_metadata_file = os.path.join(self._coverage_dir, 'coverage.em')
    self._coverage_file = os.path.join(self._coverage_dir, 'coverage.ec')
    self._coverage_console_file = os.path.join(self._coverage_dir, 'coverage.txt')
    self._coverage_xml_file = os.path.join(self._coverage_dir, 'coverage.xml')
    self._coverage_html_file = os.path.join(self._coverage_dir, 'html', 'index.html')
    self._coverage_open = options.coverage_open
    self._coverage_force = options.coverage_force

  @abstractmethod
  def instrument(self, targets, tests, compute_junit_classpath):
    pass

  @abstractmethod
  def run(self, tests_and_targets):
    pass

  @abstractmethod
  def report(self, targets, tests, tests_failed_exception):
    pass

  # Utility methods, called from subclasses
  def is_coverage_target(self, tgt):
    return (tgt.is_java or tgt.is_scala) and not tgt.is_test and not tgt.is_codegen

  def get_coverage_patterns(self, targets):
    if self._coverage_filters:
      return self._coverage_filters
    else:
      classes_under_test = set()
      classes_by_source = self._context.products.get_data('classes_by_source')

      def add_sources_under_test(tgt):
        if self.is_coverage_target(tgt):
          for source in tgt.sources_relative_to_buildroot():
            source_products = classes_by_source.get(source)
            if source_products:
              for _, classes in source_products.rel_paths():
                classes_under_test.update(_classfile_to_classname(cls) for cls in classes)

      for target in targets:
        target.walk(add_sources_under_test)
      return classes_under_test


class Emma(_Coverage):
  """Class to run coverage tests with Emma."""

  @classmethod
  def register_options(cls, register, register_jvm_tool):
    register_jvm_tool(register,
                      'emma',
                      classpath=[
                        JarDependency(org='emma', name='emma', rev='2.1.5320')
                      ])

  def instrument(self, targets, tests, compute_junit_classpath):
    junit_classpath = compute_junit_classpath()
    safe_mkdir(self._coverage_instrument_dir, clean=True)
    self._emma_classpath = self._task_exports.tool_classpath('emma')
    with binary_util.safe_args(self.get_coverage_patterns(targets),
                               self._task_exports.task_options) as patterns:
      args = [
        'instr',
        '-out', self._coverage_metadata_file,
        '-d', self._coverage_instrument_dir,
        '-cp', os.pathsep.join(junit_classpath),
        '-exit'
        ]
      for pattern in patterns:
        args.extend(['-filter', pattern])
      main = 'emma'
      execute_java = self.preferred_jvm_distribution_for_targets(targets).execute_java
      result = execute_java(classpath=self._emma_classpath,
                            main=main,
                            jvm_options=self._coverage_jvm_options,
                            args=args,
                            workunit_factory=self._context.new_workunit,
                            workunit_name='emma-instrument')
      if result != 0:
        raise TaskError("java {0} ... exited non-zero ({1})"
                        " 'failed to instrument'".format(main, result))

  def run(self, tests_and_targets):
    self._run_tests(tests_and_targets,
                    JUnitRun._MAIN,
                    classpath_prepend=[self._coverage_instrument_dir],
                    classpath_append=self._emma_classpath,
                    extra_jvm_options=['-Demma.coverage.out.file={0}'.format(self._coverage_file)])

  def report(self, targets, tests, tests_failed_exception=None):
    if tests_failed_exception:
      self._context.log.warn('Test failed: {0}'.format(str(tests_failed_exception)))
      if self._coverage_force:
        self._context.log.warn('Generating report even though tests failed')
      else:
        return
    args = [
      'report',
      '-in', self._coverage_metadata_file,
      '-in', self._coverage_file,
      '-exit'
      ]
    source_bases = set()

    def collect_source_base(target):
      if self.is_coverage_target(target):
        source_bases.add(target.target_base)
    for target in self._test_target_candidates(targets):
      target.walk(collect_source_base)
    for source_base in source_bases:
      args.extend(['-sp', source_base])

    sorting = ['-Dreport.sort', '+name,+class,+method,+block']
    args.extend(['-r', 'txt',
                 '-Dreport.txt.out.file={0}'.format(self._coverage_console_file)] + sorting)
    args.extend(['-r', 'xml', '-Dreport.xml.out.file={0}'.format(self._coverage_xml_file)])
    args.extend(['-r', 'html',
                 '-Dreport.html.out.file={0}'.format(self._coverage_html_file),
                 '-Dreport.out.encoding=UTF-8'] + sorting)

    main = 'emma'
    execute_java = self.preferred_jvm_distribution_for_targets(targets).execute_java
    result = execute_java(classpath=self._emma_classpath,
                          main=main,
                          jvm_options=self._coverage_jvm_options,
                          args=args,
                          workunit_factory=self._context.new_workunit,
                          workunit_name='emma-report')
    if result != 0:
      raise TaskError("java {0} ... exited non-zero ({1})"
                      " 'failed to generate code coverage reports'".format(main, result))

    with safe_open(self._coverage_console_file) as console_report:
      sys.stdout.write(console_report.read())
    if self._coverage_open:
      binary_util.ui_open(self._coverage_html_file)


class Cobertura(_Coverage):
  """Class to run coverage tests with cobertura."""

  @classmethod
  def register_options(cls, register, register_jvm_tool):
    slf4j_jar = JarDependency(org='org.slf4j', name='slf4j-simple', rev='1.7.5')

    def cobertura_jar(**kwargs):
      return JarDependency(org='net.sourceforge.cobertura', name='cobertura', rev='2.1.1', **kwargs)

    # The Cobertura jar needs all its dependencies when instrumenting code.
    register_jvm_tool(register,
                      'cobertura-instrument',
                      classpath=[
                        cobertura_jar(),
                        slf4j_jar
                      ])

    # Instrumented code needs cobertura.jar in the classpath to run, but not most of the
    # dependencies.
    register_jvm_tool(register,
                      'cobertura-run',
                      classpath=[
                        cobertura_jar(intransitive=True),
                        slf4j_jar
                      ])

    register_jvm_tool(register, 'cobertura-report', classpath=[cobertura_jar()])

  def __init__(self, task_exports, context):
    super(Cobertura, self).__init__(task_exports, context)
    self._coverage_datafile = os.path.join(self._coverage_dir, 'cobertura.ser')
    touch(self._coverage_datafile)
    self._rootdirs = defaultdict(OrderedSet)
    self._include_filters = []
    self._exclude_filters = []
    for filt in self._coverage_filters:
      if filt[0] == '-':
        self._exclude_filters.append(filt[1:])
      else:
        self._include_filters.append(filt)
    self._nothing_to_instrument = True

  def instrument(self, targets, tests, compute_junit_classpath):
    junit_classpath = compute_junit_classpath()
    cobertura_cp = self._task_exports.tool_classpath('cobertura-instrument')
    aux_classpath = os.pathsep.join(relativize_paths(junit_classpath, get_buildroot()))
    safe_delete(self._coverage_datafile)
    classes_by_target = self._context.products.get_data('classes_by_target')
    for target in targets:
      if self.is_coverage_target(target):
        classes_by_rootdir = classes_by_target.get(target)
        if classes_by_rootdir:
          for root, products in classes_by_rootdir.rel_paths():
            self._rootdirs[root].update(products)
    # Cobertura uses regular expressions for filters, and even then there are still problems
    # with filtering. It turned out to be easier to just select which classes to instrument
    # by filtering them here.
    # TODO(ji): Investigate again how we can use cobertura's own filtering mechanisms.
    if self._coverage_filters:
      for basedir, classes in self._rootdirs.items():
        updated_classes = []
        for cls in classes:
          does_match = False
          for positive_filter in self._include_filters:
            if fnmatch.fnmatchcase(_classfile_to_classname(cls), positive_filter):
              does_match = True
          for negative_filter in self._exclude_filters:
            if fnmatch.fnmatchcase(_classfile_to_classname(cls), negative_filter):
              does_match = False
          if does_match:
            updated_classes.append(cls)
        self._rootdirs[basedir] = updated_classes
    for basedir, classes in self._rootdirs.items():
      if not classes:
        continue  # No point in running instrumentation if there is nothing to instrument!
      self._nothing_to_instrument = False
      args = [
        '--basedir',
        basedir,
        '--datafile',
        self._coverage_datafile,
        '--auxClasspath',
        aux_classpath,
        ]
      with temporary_file_path(cleanup=False) as instrumented_classes_file:
        with file(instrumented_classes_file, 'wb') as icf:
          icf.write(('\n'.join(classes) + '\n').encode('utf-8'))
        self._context.log.debug('instrumented classes in {0}'.format(instrumented_classes_file))
        args.append('--listOfFilesToInstrument')
        args.append(instrumented_classes_file)
        main = 'net.sourceforge.cobertura.instrument.InstrumentMain'
        execute_java = self.preferred_jvm_distribution_for_targets(targets).execute_java
        result = execute_java(classpath=cobertura_cp,
                              main=main,
                              jvm_options=self._coverage_jvm_options,
                              args=args,
                              workunit_factory=self._context.new_workunit,
                              workunit_name='cobertura-instrument')
      if result != 0:
        raise TaskError("java {0} ... exited non-zero ({1})"
                        " 'failed to instrument'".format(main, result))

  def run(self, tests_and_targets):
    if self._nothing_to_instrument:
      self._context.log.warn('Nothing found to instrument, skipping tests...')
      return
    cobertura_cp = self._task_exports.tool_classpath('cobertura-run')
    self._run_tests(tests_and_targets,
                    JUnitRun._MAIN,
                    classpath_prepend=cobertura_cp,
                    extra_jvm_options=['-Dnet.sourceforge.cobertura.datafile=' + self._coverage_datafile])

  def _build_sources_by_class(self):
    """Invert classes_by_source."""

    classes_by_source = self._context.products.get_data('classes_by_source')
    source_by_class = dict()
    for source_file, source_products in classes_by_source.items():
      for root, products in source_products.rel_paths():
        for product in products:
          if not '$' in product:
            if source_by_class.get(product):
              if source_by_class.get(product) != source_file:
                self._context.log.warn(
                  'Inconsistency finding source for class {0}: already had {1}, also found {2}'
                  .format(product, source_by_class.get(product), source_file))
            else:
              source_by_class[product] = source_file
    return source_by_class

  def report(self, targets, tests, tests_failed_exception=None):
    if self._nothing_to_instrument:
      self._context.log.warn('Nothing found to instrument, skipping report...')
      return
    if tests_failed_exception:
      self._context.log.warn('Test failed: {0}'.format(tests_failed_exception))
      if self._coverage_force:
        self._context.log.warn('Generating report even though tests failed.')
      else:
        return
    cobertura_cp = self._task_exports.tool_classpath('cobertura-report')
    # Link files in the real source tree to files named using the classname.
    # Do not include class file names containing '$', as these will always have
    # a corresponding $-less class file, and they all point back to the same
    # source.
    # Put all these links to sources under self._coverage_dir/src
    all_classes = set()
    for basedir, classes in self._rootdirs.items():
      all_classes.update([cls for cls in classes if '$' not in cls])
    sources_by_class = self._build_sources_by_class()
    coverage_source_root_dir = os.path.join(self._coverage_dir, 'src')
    safe_rmtree(coverage_source_root_dir)
    for cls in all_classes:
      source_file = sources_by_class.get(cls)
      if source_file:
        # the class in @cls
        #    (e.g., 'org/pantsbuild/example/hello/welcome/WelcomeEverybody.class')
        # was compiled from the file in @source_file
        #    (e.g., 'src/scala/org/pantsbuild/example/hello/welcome/Welcome.scala')
        # Note that, in the case of scala files, the path leading up to Welcome.scala does not
        # have to match the path in the corresponding .class file AT ALL. In this example,
        # @source_file could very well have been 'src/hello-kitty/Welcome.scala'.
        # However, cobertura expects the class file path to match the corresponding source
        # file path below the source base directory(ies) (passed as (a) positional argument(s)),
        # while it still gets the source file basename from the .class file.
        # Here we create a fake hierachy under coverage_dir/src to mimic what cobertura expects.

        class_dir = os.path.dirname(cls)   # e.g., 'org/pantsbuild/example/hello/welcome'
        fake_source_directory = os.path.join(coverage_source_root_dir, class_dir)
        safe_mkdir(fake_source_directory)
        fake_source_file = os.path.join(fake_source_directory, os.path.basename(source_file))
        try:
          os.symlink(os.path.relpath(source_file, fake_source_directory),
                     fake_source_file)
        except OSError as e:
          # These warnings appear when source files contain multiple classes.
          self._context.log.warn(
            'Could not symlink {0} to {1}: {2}'.format(source_file, fake_source_file, e))
      else:
        self._context.log.error('class {0} does not exist in a source file!'.format(cls))
    report_formats = []
    report_formats.append('xml')
    report_formats.append('html')
    for report_format in report_formats:
      report_dir = os.path.join(self._coverage_dir, report_format)
      safe_mkdir(report_dir, clean=True)
      args = [
        coverage_source_root_dir,
        '--datafile',
        self._coverage_datafile,
        '--destination',
        report_dir,
        '--format',
        report_format,
        ]
      main = 'net.sourceforge.cobertura.reporting.ReportMain'
      execute_java = self.preferred_jvm_distribution_for_targets(targets).execute_java
      result = execute_java(classpath=cobertura_cp,
                            main=main,
                            jvm_options=self._coverage_jvm_options,
                            args=args,
                            workunit_factory=self._context.new_workunit,
                            workunit_name='cobertura-report-' + report_format)
      if result != 0:
        raise TaskError("java {0} ... exited non-zero ({1})"
                        " 'failed to report'".format(main, result))

    if self._coverage_open:
      coverage_html_file = os.path.join(self._coverage_dir, 'html', 'index.html')
      binary_util.ui_open(coverage_html_file)


class JUnitRun(JvmToolTaskMixin, JvmTask):
  _MAIN = 'org.pantsbuild.tools.junit.ConsoleRunner'

  @classmethod
  def register_options(cls, register):
    super(JUnitRun, cls).register_options(register)
    # TODO: Yuck, but can't be helped until we refactor the _JUnitRunner/_TaskExports mechanism.
    for c in [_JUnitRunner, _Coverage, Emma, Cobertura]:
      c.register_options(register, cls.register_jvm_tool)
    register('--coverage', action='store_true', help='Collect code coverage data.')
    register('--coverage-processor', advanced=True, default='emma',
             help='Which coverage subsystem to use.')

  @classmethod
  def subsystem_dependencies(cls):
    return super(JUnitRun, cls).subsystem_dependencies() + (DistributionLocator,)

  @classmethod
  def prepare(cls, options, round_manager):
    super(JUnitRun, cls).prepare(options, round_manager)
    round_manager.require_data('resources_by_target')

    # List of FQCN, FQCN#method, sourcefile or sourcefile#method.
    round_manager.require_data('classes_by_target')
    round_manager.require_data('classes_by_source')

  def __init__(self, *args, **kwargs):
    super(JUnitRun, self).__init__(*args, **kwargs)

    task_exports = _TaskExports(classpath=self.classpath,
                                task_options=self.get_options(),
                                jvm_options=self.jvm_options,
                                args=self.args,
                                confs=self.confs,
                                register_jvm_tool=self.register_jvm_tool,
                                tool_classpath=self.tool_classpath,
                                workdir=self.workdir)

    options = self.get_options()
    if options.coverage or options.is_flagged('coverage_open'):
      coverage_processor = options.coverage_processor
      if coverage_processor == 'emma':
        self._runner = Emma(task_exports, self.context)
      elif coverage_processor == 'cobertura':
        self._runner = Cobertura(task_exports, self.context)
      else:
        raise TaskError('unknown coverage processor {0}'.format(coverage_processor))
    else:
      self._runner = _JUnitRunner(task_exports, self.context)

  def execute(self):
    if not self.get_options().skip:
      targets = self.context.targets()
      # TODO: move this check to an optional phase in goal_runner, so
      # that missing sources can be detected early.
      for target in targets:
        if isinstance(target, junit_tests) and not target.payload.sources.source_paths:
          msg = 'JavaTests target must include a non-empty set of sources.'
          raise TargetDefinitionException(target, msg)

      self._runner.execute(targets)
