# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from abc import abstractmethod
from collections import defaultdict, namedtuple
import fnmatch
import os
import sys
import tempfile

from twitter.common.collections import OrderedSet
from twitter.common.contextutil import temporary_file
from twitter.common.dirutil import safe_delete, safe_mkdir, safe_mkdir_for, safe_open, safe_rmtree

from pants import binary_util
from pants.backend.jvm.targets.java_tests import JavaTests as junit_tests
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.java.util import execute_java
from pants.util.dirutil import safe_mkdir, safe_open


# TODO(ji): Add unit tests.
# TODO(ji): Add coverage in ci.run (https://github.com/pantsbuild/pants/issues/83)

# The helper classes (_JUnitRunner and its subclasses) need to use
# methods inherited by JUnitRun from Task. Rather than pass a reference
# to the entire Task instance, we isolate the methods that are used
# in a named tuple and pass that one around.
_TaskExports = namedtuple('_TaskExports',
                          ['classpath',
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
  def setup_parser(cls, option_group, args, mkflag):
    _Coverage.setup_parser(option_group, args, mkflag)
    option_group.add_option(mkflag('skip'), mkflag('skip', negate=True), dest='junit_run_skip',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help='[%default] Skip running tests')

    option_group.add_option(mkflag('debug'), mkflag('debug', negate=True), dest='junit_run_debug',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help='[%default] Run junit tests with a debugger')

    option_group.add_option(mkflag('fail-fast'), mkflag('fail-fast', negate=True),
                            dest='junit_run_fail_fast',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help='[%default] Fail fast on the first test failure in a suite')

    option_group.add_option(mkflag('batch-size'), type='int', default=sys.maxint,
                            dest='junit_run_batch_size',
                            help='[ALL] Runs at most this many tests in a single test process.')

    # TODO: Rename flag to jvm-options.
    option_group.add_option(mkflag('jvmargs'), dest='junit_run_jvmargs', action='append',
                            help='Runs junit tests in a jvm with these extra jvm args.')

    option_group.add_option(mkflag('test'), dest='junit_run_tests', action='append',
                            help='[%default] Force running of just these tests.  Tests can be '
                                   'specified using any of: [classname], [classname]#[methodname], '
                                   '[filename] or [filename]#[methodname]')

    xmlreport = mkflag('xmlreport')
    option_group.add_option(xmlreport, mkflag('xmlreport', negate=True),
                            dest='junit_run_xmlreport',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help='[%default] Causes an xml report to be output for each test '
                                   'class that is run.')

    option_group.add_option(mkflag('per-test-timer'), mkflag('per-test-timer', negate=True),
                            dest='junit_run_per_test_timer',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help='[%default] Shows progress and timer for each test '
                                   'class that is run.')

    option_group.add_option(mkflag('default-parallel'), mkflag('default-parallel', negate=True),
                            dest='junit_run_default_parallel',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help='[%default] Whether to run classes without @TestParallel or '
                                   '@TestSerial annotations in parallel.')

    option_group.add_option(mkflag('parallel-threads'), type='int', default=0,
                            dest='junit_run_parallel_threads',
                            help='Number of threads to run tests in parallel. 0 for autoset.')

    option_group.add_option(mkflag("test-shard"), dest="junit_run_test_shard",
                            help="Subset of tests to run, in the form M/N, 0 <= M < N."
                                   "For example, 1/3 means run tests number 2, 5, 8, 11, ...")

    option_group.add_option(mkflag('suppress-output'), mkflag('suppress-output', negate=True),
                            dest='junit_run_suppress_output',
                            action='callback', callback=mkflag.set_bool, default=True,
                            help='[%%default] Redirects test output to files '
                                 '(in .pants.d/test/junit). Implied by %s' % xmlreport)

    option_group.add_option(mkflag("arg"), dest="junit_run_arg",
                            action="append",
                            help="An arbitrary argument to pass directly to the test runner. "
                                   "This option can be specified multiple times.")

  def __init__(self, task_exports, context):
    self._task_exports = task_exports
    self._context = context
    self._junit_bootstrap_key = 'junit'
    task_exports.register_jvm_tool(self._junit_bootstrap_key,
                             context.config.getlist('junit-run', 'junit-bootstrap-tools',
                                                    default=[':junit']))
    self._jvm_args = context.config.getlist('junit-run', 'jvm_args', default=[])
    if context.options.junit_run_jvmargs:
      self._jvm_args.extend(context.options.junit_run_jvmargs)
    if context.options.junit_run_debug:
      self._jvm_args.extend(context.config.getlist('jvm', 'debug_args'))

    self._tests_to_run = context.options.junit_run_tests
    self._batch_size = context.options.junit_run_batch_size
    self._fail_fast = context.options.junit_run_fail_fast

    self._opts = []
    if context.options.junit_run_xmlreport or context.options.junit_run_suppress_output:
      if self._fail_fast:
        self._opts.append('-fail-fast')
      if context.options.junit_run_xmlreport:
        self._opts.append('-xmlreport')
      self._opts.append('-suppress-output')
      self._opts.append('-outdir')
      self._opts.append(task_exports.workdir)

    if context.options.junit_run_per_test_timer:
      self._opts.append('-per-test-timer')
    if context.options.junit_run_default_parallel:
      self._opts.append('-default-parallel')
    self._opts.append('-parallel-threads')
    self._opts.append(str(context.options.junit_run_parallel_threads))

    if context.options.junit_run_test_shard:
      self._opts.append('-test-shard')
      self._opts.append(context.options.junit_run_test_shard)

    if context.options.junit_run_arg:
      self._opts.extend(context.options.junit_run_arg)

  def execute(self, targets):
    tests = list(self._get_tests_to_run() if self._tests_to_run
                 else self._calculate_tests_from_targets(targets))
    if tests:
      bootstrapped_cp = self._task_exports.tool_classpath(self._junit_bootstrap_key)
      junit_classpath = self._task_exports.classpath(
        cp=bootstrapped_cp,
        confs=self._context.config.getlist('junit-run', 'confs', default=['default']),
        exclusives_classpath=self._task_exports.get_base_classpath_for_target(targets[0]))

      self._context.lock.release()
      self.instrument(targets, tests, junit_classpath)

      def report():
        self.report(targets, tests, junit_classpath)
      try:
        self.run(targets, tests, junit_classpath)
      except TaskError:
        report()
        raise
      else:
        report()

  def instrument(self, targets, tests, junit_classpath):
    """Called from coverage classes. Run any code instrumentation needed.

    Subclasses should override this if they need more work done."""

    pass

  def run(self, targets, tests, junit_classpath):
    """Run the tests in the appropriate environment.

    Subclasses should override this if they need more work done."""

    self._run_tests(tests, junit_classpath, JUnitRun._MAIN, jvm_args=None)

  def report(self, targets, tests, junit_classpath):
    """Post-processing of any test output.

    Subclasses should override this if they need anything done here."""

    pass

  def _run_tests(self, tests, classpath, main, jvm_args=None):
    # TODO(John Sirois): Integrated batching with the test runner.  As things stand we get
    # results summaries for example for each batch but no overall summary.
    # http://jira.local.twitter.com/browse/AWESOME-1114
    result = 0
    for batch in self._partition(tests):
      with binary_util.safe_args(batch) as batch_tests:
        result += abs(execute_java(
          classpath=classpath,
          main=main,
          jvm_options=(jvm_args or []) + self._jvm_args,
          args=self._opts + batch_tests,
          workunit_factory=self._context.new_workunit,
          workunit_name='run',
          workunit_labels=[WorkUnit.TEST]
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
  def setup_parser(cls, option_group, args, mkflag):
    coverage_patterns = mkflag('coverage-patterns')
    option_group.add_option(coverage_patterns, dest='junit_run_coverage_patterns',
                            action='append',
                            help='By default all non-test code depended on by the selected tests '
                                 'is measured for coverage during the test run.  By specifying '
                                 'coverage patterns you can select which classes and packages '
                                 'should be counted.  Values should be class name prefixes in '
                                 'dotted form with ? and * wildcard support. If preceded with a - '
                                 'the pattern is excluded. '
                                 'For example, to include all code in com.twitter.raven except '
                                 'claws and the eye you would use: '
                                 '%(flag)s=com.twitter.raven.* '
                                 '%(flag)s=-com.twitter.raven.claw '
                                 '%(flag)s=-com.twitter.raven.Eye'
                                 'This option can be specified multiple times. ' % dict(
                                    flag=coverage_patterns
                                 ))

    option_group.add_option(mkflag('coverage-console'), mkflag('coverage-console', negate=True),
                            dest='junit_run_coverage_console',
                            action='callback', callback=mkflag.set_bool, default=True,
                            help='[%default] Outputs a simple coverage report to the console.')

    option_group.add_option(mkflag('coverage-xml'), mkflag('coverage-xml', negate=True),
                            dest='junit_run_coverage_xml',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help='[%%default] Produces an xml coverage report.')

    coverage_html_flag = mkflag('coverage-html')
    option_group.add_option(coverage_html_flag, mkflag('coverage-html', negate=True),
                            dest='junit_run_coverage_html',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help='[%%default] Produces an html coverage report.')

    option_group.add_option(mkflag('coverage-html-open'), mkflag('coverage-html-open', negate=True),
                            dest='junit_run_coverage_html_open',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help='[%%default] Tries to open the generated html coverage report, '
                                   'implies %s.' % coverage_html_flag)

  def __init__(self, task_exports, context):
    super(_Coverage, self).__init__(task_exports, context)
    self._coverage = context.options.junit_run_coverage
    self._coverage_filters = context.options.junit_run_coverage_patterns or []
    self._coverage_dir = os.path.join(task_exports.workdir, 'coverage')
    self._coverage_instrument_dir = os.path.join(self._coverage_dir, 'classes')
    # TODO(ji): These may need to be transferred down to the Emma class, as the suffixes
    # may be emma-specific. Resolve when we also provide cobertura support.
    self._coverage_metadata_file = os.path.join(self._coverage_dir, 'coverage.em')
    self._coverage_file = os.path.join(self._coverage_dir, 'coverage.ec')
    self._coverage_report_console = context.options.junit_run_coverage_console
    self._coverage_console_file = os.path.join(self._coverage_dir, 'coverage.txt')

    self._coverage_report_xml = context.options.junit_run_coverage_xml
    self._coverage_xml_file = os.path.join(self._coverage_dir, 'coverage.xml')

    self._coverage_report_html_open = context.options.junit_run_coverage_html_open
    self._coverage_report_html = (self._coverage_report_html_open or
                                  context.options.junit_run_coverage_html)
    self._coverage_html_file = os.path.join(self._coverage_dir, 'html', 'index.html')

  @abstractmethod
  def instrument(self, targets, tests, junit_classpath):
    pass

  @abstractmethod
  def run(self, targets, tests, junit_classpath):
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
    task_exports.register_jvm_tool(self._emma_bootstrap_key,
                                   context.config.getlist('junit-run', 'emma-bootstrap-tools',
                                                          default=[':emma']))

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

  def run(self, targets, tests, junit_classpath):
    self._run_tests(tests,
                    [self._coverage_instrument_dir] + junit_classpath + self._emma_classpath,
                    JUnitRun._MAIN,
                    jvm_args=['-Demma.coverage.out.file=%s' % self._coverage_file])

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
    task_exports.register_jvm_tool(self._cobertura_bootstrap_key,
                                   context.config.getlist('junit-run', 'cobertura-bootstrap-tools',
                                                          default=[':cobertura']))
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

  def run(self, targets, tests, junit_classpath):
    self._run_tests(tests,
                    self._cobertura_classpath + junit_classpath,
                    JUnitRun._MAIN,
                    jvm_args=['-Dnet.sourceforge.cobertura.datafile=' + self._coverage_datafile])

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
  def setup_parser(cls, option_group, args, mkflag):
    _JUnitRunner.setup_parser(option_group, args, mkflag)
    option_group.add_option(mkflag('coverage'), mkflag('coverage', negate=True),
                            dest='junit_run_coverage',
                            action='callback', callback=mkflag.set_bool, default=False,
                            help='[%default] Collects code coverage data')

    option_group.add_option(mkflag('coverage-processor'),
                            dest='junit_coverage_processor',
                            default='emma',
                            help='[%default] Which coverage subsystem to use')

  def __init__(self, context, workdir):
    super(JUnitRun, self).__init__(context, workdir)

    self._context = context
    task_exports = _TaskExports(classpath=self.classpath,
                                get_base_classpath_for_target=self.get_base_classpath_for_target,
                                register_jvm_tool=self.register_jvm_tool,
                                tool_classpath=self.tool_classpath,
                                workdir=self.workdir)

    options = self._context.options
    if options.junit_run_coverage or options.junit_run_coverage_html_open:
      if options.junit_coverage_processor == 'emma':
        self._runner = Emma(task_exports, self._context)
      elif options.junit_coverage_processor == 'cobertura':
        self._runner = Cobertura(task_exports, self._context)
      else:
        raise TaskError('unknown coverage processor %s' % context.options.junit_coverage_processor)
    else:
      self._runner = _JUnitRunner(task_exports, self._context)

  def prepare(self, round_manager):
    super(JUnitRun, self).prepare(round_manager)
    round_manager.require_data('resources_by_target')

    # List of FQCN, FQCN#method, sourcefile or sourcefile#method.
    round_manager.require_data('classes_by_target')
    round_manager.require_data('classes_by_source')

  def execute(self):
    if not self._context.options.junit_run_skip:
      targets = self.context.targets()
      self._runner.execute(targets)
