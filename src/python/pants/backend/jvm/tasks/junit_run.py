# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from abc import abstractmethod
from collections import defaultdict, namedtuple
import copy
import fnmatch
import os
import sys

from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_delete, safe_rmtree

from pants import binary_util
from pants.backend.jvm.targets.java_tests import JavaTests as junit_tests
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.java.util import execute_java
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_mkdir, safe_open


_CWD_NOT_PRESENT='CWD NOT PRESENT'

# TODO(ji): Add unit tests.
# TODO(ji): Add coverage in ci.run (https://github.com/pantsbuild/pants/issues/83)

# The helper classes (_JUnitRunner and its subclasses) need to use
# methods inherited by JUnitRun from Task. Rather than pass a reference
# to the entire Task instance, we isolate the methods that are used
# in a named tuple and pass that one around.

# TODO(benjy): Why? This seems unnecessarily clunky. The runners only exist because we can't
# (yet?) pick a Task type based on cmd-line flags. But they act "as-if" they were Task types,
# so it seems prefectly reasonable for them to have a reference to the task.
# This trick just makes debugging harder, and requires extra work when a runner implementation
# needs some new thing from the task.
_TaskExports = namedtuple('_TaskExports',
                          ['classpath',
                           'task_options',
                           'jvm_options',
                           'args',
                           'confs',
                           'get_base_classpath_for_target',
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
  def register_options(cls, register):
    _Coverage.register_options(register)
    register('--skip', action='store_true', help='Skip running junit.')
    register('--fail-fast', action='store_true',
             help='Fail fast on the first test failure in a suite.')
    register('--batch-size', type=int, default=sys.maxint,
             help='Run at most this many tests in a single test process.')
    register('--test', action='append',
             help='Force running of just these tests.  Tests can be specified using any of: '
                  '[classname], [classname]#[methodname], [filename] or [filename]#[methodname]')
    register('--xml-report', action='store_true', help='Output an XML report for the test run.')
    register('--per-test-timer', action='store_true', help='Show progress and timer for each test.')
    register('--default-parallel', action='store_true',
             help='Run classes without @TestParallel or @TestSerial annotations in parallel.')
    register('--parallel-threads', type=int, default=0,
             help='Number of threads to run tests in parallel. 0 for autoset.')
    register('--test-shard',
             help='Subset of tests to run, in the form M/N, 0 <= M < N. '
                  'For example, 1/3 means run tests number 2, 5, 8, 11, ...')
    register('--suppress-output', action='store_true', default=True,
             help='Redirect test output to files in .pants.d/test/junit. Implied by --xml-report.')
    register('--cwd', default=_CWD_NOT_PRESENT, nargs='?',
             help='Set the working directory. If no argument is passed, use the first target path.')

  def register_jvm_tool(self, key, ini_section, ini_key, default):
    tool = self._context.config.getlist(ini_section, ini_key, default)
    self._task_exports.register_jvm_tool(key,
                                         tool,
                                         ini_section=ini_section,
                                         ini_key=ini_key)

  def __init__(self, task_exports, context):
    self._task_exports = task_exports
    self._context = context
    self._junit_bootstrap_key = 'junit'
    self.register_jvm_tool(key=self._junit_bootstrap_key,
                           ini_section='junit-run',
                           ini_key='junit-bootstrap-tools',
                           default=['//:junit'])

    options = task_exports.task_options
    self._tests_to_run = options.test
    self._batch_size = options.batch_size
    self._fail_fast = options.fail_fast
    self._cwd_opt = options.cwd
    self._args = copy.copy(task_exports.args)
    if options.xml_report or options.suppress_output:
      if self._fail_fast:
        self._args.append('-fail-fast')
      if options.xml_report:
        self._args.append('-xmlreport')
      self._args.append('-suppress-output')
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
    working_dir = None
    if self._cwd_opt != _CWD_NOT_PRESENT:
      working_dir = self._cwd_opt
      if not working_dir and targets:
        working_dir = targets[0].address.spec_path
    # For running the junit tests, we're only interested in
    # java_tests/junit_tests targets.
    #
    # But if coverage options are specified, the original
    # behavior is that in addition to the junit runs, the coverage
    # tools would also look into additional targets such as sources.
    #
    # Thus, we filter out the non-java-tests targets first but
    # keep the original targets set intact for coverages.
    java_tests_targets = list(self._test_target_candidates(targets))
    tests = list(self._get_tests_to_run() if self._tests_to_run
                 else self._calculate_tests_from_targets(java_tests_targets))
    if tests:
      bootstrapped_cp = self._task_exports.tool_classpath(self._junit_bootstrap_key)
      junit_classpath = self._task_exports.classpath(
        cp=bootstrapped_cp,
        confs=self._task_exports.confs,
        exclusives_classpath=self._task_exports.get_base_classpath_for_target(java_tests_targets[0]))

      self._context.release_lock()
      self.instrument(targets, tests, junit_classpath)

      def report():
        self.report(targets, tests, junit_classpath)
      try:
        self.run(tests, junit_classpath, cwd=working_dir)
      except TaskError:
        report()
        raise
      else:
        report()

  def instrument(self, targets, tests, junit_classpath):
    """Called from coverage classes. Run any code instrumentation needed.

    Subclasses should override this if they need more work done."""

    pass

  def run(self, tests, junit_classpath, cwd=None):
    """Run the tests in the appropriate environment.

    Subclasses should override this if they need more work done.

    :param tests: an iterable that contains all the test class names
      extracted from the testing targets.
    :param junit_classpath: the collective classpath value under which
      the junit will be executed.
    """

    self._run_tests(tests, junit_classpath, JUnitRun._MAIN, cwd=cwd)

  def report(self, targets, tests, junit_classpath):
    """Post-processing of any test output.

    Subclasses should override this if they need anything done here."""

    pass

  def _run_tests(self, tests, classpath, main, extra_jvm_options=None, cwd=None):
    # TODO(John Sirois): Integrated batching with the test runner.  As things stand we get
    # results summaries for example for each batch but no overall summary.
    # http://jira.local.twitter.com/browse/AWESOME-1114
    extra_jvm_options = extra_jvm_options or []
    result = 0
    cwd = cwd or get_buildroot()
    for batch in self._partition(tests):
      with binary_util.safe_args(batch) as batch_tests:
        result += abs(execute_java(
          classpath=classpath,
          main=main,
          jvm_options=self._task_exports.jvm_options + extra_jvm_options,
          args=self._args + batch_tests,
          workunit_factory=self._context.new_workunit,
          workunit_name='run',
          workunit_labels=[WorkUnit.TEST],
          cwd=cwd
        ))
        if result != 0 and self._fail_fast:
          break
    if result != 0:
      raise TaskError('java %s ... exited non-zero (%i)' % (main, result))

  def _partition(self, tests):
    stride = min(self._batch_size, len(tests))
    for i in range(0, len(tests), stride):
      yield tests[i:i+stride]

  def _get_tests_to_run(self):
    for test_spec in self._tests_to_run:
      for c in self._interpret_test_spec(test_spec):
        yield c

  def _test_target_candidates(self, targets):
    for target in targets:
      if isinstance(target, junit_tests):
        yield target

  def _calculate_tests_from_targets(self, targets):
    targets_to_classes = self._context.products.get_data('classes_by_target')
    for target in self._test_target_candidates(targets):
      target_products = targets_to_classes.get(target)
      if target_products:
        for _, classes in target_products.rel_paths():
          for cls in classes:
            yield _classfile_to_classname(cls)

  def _classnames_from_source_file(self, srcfile):
    relsrc = os.path.relpath(srcfile, get_buildroot()) if os.path.isabs(srcfile) else srcfile
    source_products = self._context.products.get_data('classes_by_source').get(relsrc)
    if not source_products:
      # It's valid - if questionable - to have a source file with no classes when, for
      # example, the source file has all its code commented out.
      self._context.log.warn('Source file %s generated no classes' % srcfile)
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


class _Coverage(_JUnitRunner):
  """Base class for emma-like coverage processors. Do not instantiate."""

  @classmethod
  def register_options(cls, register):
    register('--coverage-patterns', action='append',
             help='Restrict coverage measurement. Values are class name prefixes in dotted form '
                  'with ? and * wildcards. If preceded with a - the pattern is excluded. For '
                  'example, to include all code in com.pants.raven except claws and the eye you '
                  'would use: {flag}=com.pants.raven.* {flag}=-com.pants.raven.claw '
                  '{flag}=-com.pants.raven.Eye.'.format(flag='--coverage_patterns'))
    register('--coverage-console', action='store_true', default=True,
             help='Output a simple coverage report to the console.')
    register('--coverage-xml', action='store_true',
             help='Output an XML coverage report.')
    register('--coverage-html', action='store_true',
            help='Output an HTML coverage report.')
    register('--coverage-html-open', action='store_true',
             help='Open the generated HTML coverage report in a browser. Implies --coverage-html.')

  def __init__(self, task_exports, context):
    super(_Coverage, self).__init__(task_exports, context)
    options = task_exports.task_options
    self._coverage = options.coverage
    self._coverage_filters = options.coverage_patterns or []
    self._coverage_dir = os.path.join(task_exports.workdir, 'coverage')
    self._coverage_instrument_dir = os.path.join(self._coverage_dir, 'classes')
    # TODO(ji): These may need to be transferred down to the Emma class, as the suffixes
    # may be emma-specific. Resolve when we also provide cobertura support.
    self._coverage_metadata_file = os.path.join(self._coverage_dir, 'coverage.em')
    self._coverage_file = os.path.join(self._coverage_dir, 'coverage.ec')
    self._coverage_report_console = options.coverage_console
    self._coverage_console_file = os.path.join(self._coverage_dir, 'coverage.txt')

    self._coverage_report_xml = options.coverage_xml
    self._coverage_xml_file = os.path.join(self._coverage_dir, 'coverage.xml')

    self._coverage_report_html_open = options.coverage_html_open
    self._coverage_report_html = self._coverage_report_html_open or options.coverage_html
    self._coverage_html_file = os.path.join(self._coverage_dir, 'html', 'index.html')

  @abstractmethod
  def instrument(self, targets, tests, junit_classpath):
    pass

  @abstractmethod
  def run(self, tests, junit_classpath, cwd=None):
    pass

  @abstractmethod
  def report(self, targets, tests, junit_classpath):
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

  def __init__(self, task_exports, context):
    super(Emma, self).__init__(task_exports, context)
    self._emma_bootstrap_key = 'emma'
    self.register_jvm_tool(self._emma_bootstrap_key,
                           ini_section='junit-run',
                           ini_key='emma-bootstrap-tools',
                           default=['//:emma'])

  def instrument(self, targets, tests, junit_classpath):
    safe_mkdir(self._coverage_instrument_dir, clean=True)
    self._emma_classpath = self._task_exports.tool_classpath(self._emma_bootstrap_key)
    with binary_util.safe_args(self.get_coverage_patterns(targets)) as patterns:
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
      result = execute_java(classpath=self._emma_classpath, main=main, args=args,
                            workunit_factory=self._context.new_workunit,
                            workunit_name='emma-instrument')
      if result != 0:
        raise TaskError("java %s ... exited non-zero (%i)"
                        " 'failed to instrument'" % (main, result))

  def run(self, tests, junit_classpath, cwd=None):
    self._run_tests(tests,
                    [self._coverage_instrument_dir] + junit_classpath + self._emma_classpath,
                    JUnitRun._MAIN,
                    extra_jvm_options=['-Demma.coverage.out.file={0}'.format(self._coverage_file)],
                    cwd=cwd)

  def report(self, targets, tests, junit_classpath):
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
    if self._coverage_report_console:
      args.extend(['-r', 'txt',
                   '-Dreport.txt.out.file=%s' % self._coverage_console_file] + sorting)
    if self._coverage_report_xml:
      args.extend(['-r', 'xml', '-Dreport.xml.out.file=%s' % self._coverage_xml_file])
    if self._coverage_report_html:
      args.extend(['-r', 'html',
                   '-Dreport.html.out.file=%s' % self._coverage_html_file,
                   '-Dreport.out.encoding=UTF-8'] + sorting)

    main = 'emma'
    result = execute_java(classpath=self._emma_classpath, main=main, args=args,
                          workunit_factory=self._context.new_workunit,
                          workunit_name='emma-report')
    if result != 0:
      raise TaskError("java %s ... exited non-zero (%i)"
                      " 'failed to generate code coverage reports'" % (main, result))

    if self._coverage_report_console:
      with safe_open(self._coverage_console_file) as console_report:
        sys.stdout.write(console_report.read())
    if self._coverage_report_html_open:
      binary_util.ui_open(self._coverage_html_file)


class Cobertura(_Coverage):
  """Class to run coverage tests with cobertura."""

  def __init__(self, task_exports, context):
    super(Cobertura, self).__init__(task_exports, context)
    self._cobertura_bootstrap_key = 'cobertura'
    self._coverage_datafile = os.path.join(self._coverage_dir, 'cobertura.ser')
    self.register_jvm_tool(self._cobertura_bootstrap_key,
                           ini_section='junit-run',
                           ini_key='cobertura-bootstrap-tools',
                           default=['//:cobertura'])
    self._rootdirs = defaultdict(OrderedSet)
    self._include_filters = []
    self._exclude_filters = []
    for filt in self._coverage_filters:
      if filt[0] == '-':
        self._exclude_filters.append(filt[1:])
      else:
        self._include_filters.append(filt)

  def instrument(self, targets, tests, junit_classpath):
    self._cobertura_classpath = self._task_exports.tool_classpath(self._cobertura_bootstrap_key)
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
      args = [
        '--basedir',
        basedir,
        '--datafile',
        self._coverage_datafile,
        ]
      with temporary_file() as fd:
        fd.write('\n'.join(classes) + '\n')
        args.append('--listOfFilesToInstrument')
        args.append(fd.name)
        main = 'net.sourceforge.cobertura.instrument.InstrumentMain'
        result = execute_java(classpath=self._cobertura_classpath + junit_classpath,
                              main=main,
                              args=args,
                              workunit_factory=self._context.new_workunit,
                              workunit_name='cobertura-instrument')
      if result != 0:
        raise TaskError("java %s ... exited non-zero (%i)"
                        " 'failed to instrument'" % (main, result))

  def run(self, tests, junit_classpath, cwd=None):
    self._run_tests(tests,
                    self._cobertura_classpath + junit_classpath,
                    JUnitRun._MAIN,
                    extra_jvm_options=['-Dnet.sourceforge.cobertura.datafile=' + self._coverage_datafile],
                    cwd=cwd)

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
                  'Inconsistency finding source for class %s: already had %s, also found %s',
                  (product, source_by_class.get(product), source_file))
            else:
              source_by_class[product] = source_file
    return source_by_class

  def report(self, targets, tests, junit_classpath):
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
        #    (e.g., 'com/pants/example/hello/welcome/WelcomeEverybody.class')
        # was compiled from the file in @source_file
        #    (e.g., 'src/scala/com/pants/example/hello/welcome/Welcome.scala')
        # Note that, in the case of scala files, the path leading up to Welcome.scala does not
        # have to match the path in the corresponding .class file AT ALL. In this example,
        # @source_file could very well have been 'src/hello-kitty/Welcome.scala'.
        # However, cobertura expects the class file path to match the corresponding source
        # file path below the source base directory(ies) (passed as (a) positional argument(s)),
        # while it still gets the source file basename from the .class file.
        # Here we create a fake hierachy under coverage_dir/src to mimic what cobertura expects.

        class_dir = os.path.dirname(cls)   # e.g., 'com/pants/example/hello/welcome'
        fake_source_directory = os.path.join(coverage_source_root_dir, class_dir)
        safe_mkdir(fake_source_directory)
        fake_source_file = os.path.join(fake_source_directory, os.path.basename(source_file))
        try:
          os.symlink(os.path.relpath(source_file, fake_source_directory),
                     fake_source_file)
        except OSError as e:
          # These warnings appear when source files contain multiple classes.
          self._context.log.warn(
            'Could not symlink %s to %s: %s' %
            (source_file, fake_source_file, e))
      else:
        self._context.log.error('class %s does not exist in a source file!' % cls)
    report_formats = []
    if self._coverage_report_xml:
      report_formats.append('xml')
    if self._coverage_report_html:
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
      result = execute_java(classpath=self._cobertura_classpath,
                            main=main,
                            args=args,
                            workunit_factory=self._context.new_workunit,
                            workunit_name='cobertura-report-' + report_format)
      if result != 0:
        raise TaskError("java %s ... exited non-zero (%i)"
                        " 'failed to report'" % (main, result))


class JUnitRun(JvmTask, JvmToolTaskMixin):
  _MAIN = 'com.twitter.common.junit.runner.ConsoleRunner'

  @classmethod
  def register_options(cls, register):
    super(JUnitRun, cls).register_options(register)
    _JUnitRunner.register_options(register)
    register('--coverage', action='store_true', help='Collect code coverage data.')
    register('--coverage-processor', default='emma', help='Which coverage subsystem to use.')


  def __init__(self, *args, **kwargs):
    super(JUnitRun, self).__init__(*args, **kwargs)

    task_exports = _TaskExports(classpath=self.classpath,
                                task_options=self.get_options(),
                                jvm_options=self.jvm_options,
                                args=self.args,
                                confs=self.confs,
                                get_base_classpath_for_target=self.get_base_classpath_for_target,
                                register_jvm_tool=self.register_jvm_tool,
                                tool_classpath=self.tool_classpath,
                                workdir=self.workdir)

    options = self.get_options()
    if options.coverage or options.coverage_html_open:
      coverage_processor = options.coverage_processor
      if coverage_processor == 'emma':
        self._runner = Emma(task_exports, self.context)
      elif coverage_processor == 'cobertura':
        self._runner = Cobertura(task_exports, self.context)
      else:
        raise TaskError('unknown coverage processor %s' % coverage_processor)
    else:
      self._runner = _JUnitRunner(task_exports, self.context)

  def prepare(self, round_manager):
    super(JUnitRun, self).prepare(round_manager)
    round_manager.require_data('resources_by_target')

    # List of FQCN, FQCN#method, sourcefile or sourcefile#method.
    round_manager.require_data('classes_by_target')
    round_manager.require_data('classes_by_source')

  def execute(self):
    if not self.get_options().skip:
      targets = self.context.targets()
      self._runner.execute(targets)
