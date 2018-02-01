# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import os
import shutil
import time
import traceback
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from textwrap import dedent

from six import StringIO
from six.moves import configparser
from twitter.common.collections import OrderedSet

from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.gather_sources import GatherSources
from pants.backend.python.tasks.pytest_prep import PytestPrep
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import ErrorWhileTesting, TaskError
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.base.hash_utils import Sharder
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.target import Target
from pants.task.task import Task
from pants.task.testrunner_task_mixin import PartitionedTestRunnerTaskMixin, TestResult
from pants.util.contextutil import pushd, temporary_dir, temporary_file
from pants.util.dirutil import mergetree, safe_mkdir, safe_mkdir_for
from pants.util.memo import memoized_method, memoized_property
from pants.util.objects import datatype
from pants.util.process_handler import SubprocessProcessHandler
from pants.util.strutil import safe_shlex_split
from pants.util.xml_parser import XmlParser


class _Workdirs(datatype('_Workdirs', ['root_dir', 'partition'])):
  @classmethod
  def for_partition(cls, work_dir, partition):
    root_dir = os.path.join(work_dir, Target.maybe_readable_identify(partition))
    safe_mkdir(root_dir, clean=False)
    return cls(root_dir=root_dir, partition=partition)

  @memoized_method
  def target_set_id(self, *targets):
    return Target.maybe_readable_identify(targets or self.partition)

  @memoized_method
  def junitxml_path(self, *targets):
    xml_path = os.path.join(self.root_dir, 'junitxml',
                            'TEST-{}.xml'.format(self.target_set_id(*targets)))
    safe_mkdir_for(xml_path)
    return xml_path

  @memoized_property
  def coverage_path(self):
    coverage_workdir = os.path.join(self.root_dir, 'coverage')
    safe_mkdir(coverage_workdir)
    return coverage_workdir

  def files(self):
    def files_iter():
      for dir_path, _, file_names in os.walk(self.root_dir):
        for filename in file_names:
          yield os.path.join(dir_path, filename)
    return list(files_iter())


class PytestResult(TestResult):
  _SUCCESS_EXIT_CODES = (
    0,

    # This is returned by pytest when no tests are collected (EXIT_NOTESTSCOLLECTED).
    # We already short-circuit test runs with no test _targets_ to return 0 emulated exit codes and
    # we should do the same for cases when there are test targets but tests themselves have been
    # de-selected out of band via `py.test -k`.
    5
  )

  @classmethod
  def _map_exit_code(cls, value):
    return 0 if value in cls._SUCCESS_EXIT_CODES else value


class PytestRun(PartitionedTestRunnerTaskMixin, Task):

  @classmethod
  def implementation_version(cls):
    return super(PytestRun, cls).implementation_version() + [('PytestRun', 2)]

  @classmethod
  def register_options(cls, register):
    super(PytestRun, cls).register_options(register)

    # NB: We always produce junit xml privately, and if this option is specified, we then copy
    # it to the user-specified directory, post any interaction with the cache to retrieve the
    # privately generated and cached xml files. As such, this option is not part of the
    # fingerprint.
    register('--junit-xml-dir', metavar='<DIR>',
             help='Specifying a directory causes junit xml results files to be emitted under '
                  'that dir for each test run.')

    register('--profile', metavar='<FILE>', fingerprint=True,
             help="Specifying a file path causes tests to be profiled with the profiling data "
                  "emitted to that file (prefix). Note that tests may run in a different cwd, so "
                  "it's best to use an absolute path to make it easy to find the subprocess "
                  "profiles later.")

    register('--options', type=list, fingerprint=True, help='Pass these options to pytest.')

    register('--coverage', fingerprint=True,
             help='Emit coverage information for specified packages or directories (absolute or '
                  'relative to the build root).  The special value "auto" indicates that Pants '
                  'should attempt to deduce which packages to emit coverage for.')
    # For a given --coverage specification (which is fingerprinted), we will always copy the
    # associated generated and cached --coverage files to this directory post any interaction with
    # the cache to retrieve the coverage files. As such, this option is not part of the fingerprint.
    register('--coverage-output-dir', metavar='<DIR>', default=None,
             help='Directory to emit coverage reports to. '
             'If not specified, a default within dist is used.')

    register('--test-shard', fingerprint=True,
             help='Subset of tests to run, in the form M/N, 0 <= M < N. For example, 1/3 means '
                  'run tests number 2, 5, 8, 11, ...')

  @classmethod
  def supports_passthru_args(cls):
    return True

  @classmethod
  def prepare(cls, options, round_manager):
    super(PytestRun, cls).prepare(options, round_manager)
    round_manager.require_data(PytestPrep.PYTEST_BINARY)

  def _test_target_filter(self):
    def target_filter(target):
      return isinstance(target, PythonTests)

    return target_filter

  def _validate_target(self, target):
    pass

  class InvalidShardSpecification(TaskError):
    """Indicates an invalid `--test-shard` option."""

  DEFAULT_COVERAGE_CONFIG = dedent(b"""
    [run]
    branch = True
    timid = True

    [report]
    exclude_lines =
        def __repr__
        raise NotImplementedError
    """)

  @staticmethod
  def _format_string_list(values):
    # The coverage rc ini files accept "Multi-valued strings" - ie: lists of strings - denoted by
    # indenting values on multiple lines like so:
    # [section]
    # name =
    #   value1
    #   value2
    #
    # See http://nedbatchelder.com/code/coverage/config.html for details.
    return '\n\t{values}'.format(values='\n\t'.join(values))

  @property
  def _debug(self):
    return self.get_options().level == 'debug'

  def _generate_coverage_config(self, source_mappings):
    cp = configparser.SafeConfigParser()
    cp.readfp(StringIO(self.DEFAULT_COVERAGE_CONFIG))

    # We use the source_mappings to setup the `combine` coverage command to transform paths in
    # coverage data files into canonical form.
    # See the "[paths]" entry here: http://nedbatchelder.com/code/coverage/config.html for details.
    cp.add_section('paths')
    for canonical, alternate in source_mappings.items():
      key = canonical.replace(os.sep, '.')

      # For the benefit of macos testing, add the 'real' paths as equivalents.
      paths = OrderedSet([canonical,
                          alternate,
                          os.path.realpath(canonical),
                          os.path.realpath(alternate)])

      cp.set('paths', key, self._format_string_list(paths))

    # See the debug options here: http://nedbatchelder.com/code/coverage/cmd.html#cmd-run-debug
    if self._debug:
      debug_options = self._format_string_list([
        # Dumps the coverage config realized values.
        'config',
        # Logs which files are skipped or traced and why.
        'trace'])
      cp.set('run', 'debug', debug_options)

    return cp

  @contextmanager
  def _cov_setup(self, workdirs, source_mappings, coverage_sources=None):
    cp = self._generate_coverage_config(source_mappings=source_mappings)
    # Note that it's important to put the tmpfile under the workdir, because pytest
    # uses all arguments that look like paths to compute its rootdir, and we want
    # it to pick the buildroot.
    with temporary_file(root_dir=workdirs.root_dir) as fp:
      cp.write(fp)
      fp.close()
      coverage_rc = fp.name
      # Note that --cov-report= with no value turns off terminal reporting, which
      # we handle separately.
      args = ['--cov-report=', '--cov-config', coverage_rc]
      for module in coverage_sources:
        args.extend(['--cov', module])
      yield args, coverage_rc

  @contextmanager
  def _maybe_emit_coverage_data(self, workdirs, targets, pex):
    coverage = self.get_options().coverage
    if coverage is None:
      yield []
      return

    def pex_src_root(tgt):
      return os.path.relpath(self._source_chroot_path([tgt]), get_buildroot())

    source_mappings = {}
    for target in targets:
      libs = (tgt for tgt in target.closure()
              if tgt.has_sources('.py') and not isinstance(tgt, PythonTests))
      for lib in libs:
        source_mappings[lib.target_base] = pex_src_root(lib)

    def ensure_trailing_sep(path):
      return path if path.endswith(os.path.sep) else path + os.path.sep

    if coverage == 'auto':
      def compute_coverage_sources(tgt):
        if tgt.coverage:
          return tgt.coverage
        else:
          # This makes the assumption that tests/python/<tgt> will be testing src/python/<tgt>.
          # Note in particular that this doesn't work for pants' own tests, as those are under
          # the top level package 'pants_tests', rather than just 'pants'.
          # TODO(John Sirois): consider failing fast if there is no explicit coverage scheme;
          # but also  consider supporting configuration of a global scheme whether that be parallel
          # dirs/packages or some arbitrary function that can be registered that takes a test target
          # and hands back the source packages or paths under test.
          return set(os.path.dirname(s).replace(os.sep, '.')
                     for s in tgt.sources_relative_to_source_root())
      coverage_sources = set(itertools.chain(*[compute_coverage_sources(t) for t in targets]))
    else:
      coverage_sources = []
      for source in coverage.split(','):
        if os.path.isdir(source):
          # The source is a dir, so correct its prefix for the chroot.
          # E.g. if source is /path/to/src/python/foo/bar or src/python/foo/bar then
          # rel_source is src/python/foo/bar, and ...
          rel_source = os.path.relpath(source, get_buildroot())
          rel_source = ensure_trailing_sep(rel_source)
          found_target_base = False
          for target_base, pex_root in source_mappings.items():
            prefix = ensure_trailing_sep(target_base)
            if rel_source.startswith(prefix):
              # ... rel_source will match on prefix=src/python/ ...
              suffix = rel_source[len(prefix):]
              # ... suffix will equal foo/bar ...
              coverage_sources.append(os.path.join(pex_root, suffix))
              found_target_base = True
              # ... and we end up appending <pex_src_root>/foo/bar to the coverage_sources.
              break
          if not found_target_base:
            self.context.log.warn('Coverage path {} is not in any target. Skipping.'.format(source))
        else:
          # The source is to be interpreted as a package name.
          coverage_sources.append(source)

    with self._cov_setup(workdirs,
                         source_mappings,
                         coverage_sources=coverage_sources) as (args, coverage_rc):
      try:
        yield args
      finally:
        env = {
          'PEX_MODULE': 'coverage.cmdline:main'
        }
        def coverage_run(subcommand, arguments):
          return self._pex_run(pex,
                               workunit_name='coverage-{}'.format(subcommand),
                               args=[subcommand] + arguments,
                               env=env)

        # On failures or timeouts, the .coverage file won't be written.
        if not os.path.exists('.coverage'):
          self.context.log.warn('No .coverage file was found! Skipping coverage reporting.')
        else:
          # Normalize .coverage.raw paths using combine and `paths` config in the rc file.
          # This swaps the /tmp pex chroot source paths for the local original source paths
          # the pex was generated from and which the user understands.
          shutil.move('.coverage', '.coverage.raw')
          # N.B.: This transforms the contents of .coverage.raw and moves it back into .coverage.
          coverage_run('combine', ['--rcfile', coverage_rc])

          coverage_run('report', ['-i', '--rcfile', coverage_rc])

          coverage_workdir = workdirs.coverage_path
          coverage_run('html', ['-i', '--rcfile', coverage_rc, '-d', coverage_workdir])
          coverage_xml = os.path.join(coverage_workdir, 'coverage.xml')
          coverage_run('xml', ['-i', '--rcfile', coverage_rc, '-o', coverage_xml])

  def _get_shard_conftest_content(self):
    shard_spec = self.get_options().test_shard
    if shard_spec is None:
      return ''

    try:
      sharder = Sharder(shard_spec)
      if sharder.nshards < 2:
        return ''
      return dedent("""

        ### GENERATED BY PANTS ###

        def pytest_report_header(config):
          return 'shard: {shard} of {nshards} (0-based shard numbering)'

        def pytest_collection_modifyitems(session, config, items):
          total_count = len(items)
          removed = 0
          def is_conftest(itm):
            return itm.fspath and itm.fspath.basename == 'conftest.py'
          for i, item in enumerate(list(x for x in items if not is_conftest(x))):
            if i % {nshards} != {shard}:
              del items[i - removed]
              removed += 1
          reporter = config.pluginmanager.getplugin('terminalreporter')
          reporter.write_line('Only executing {{}} of {{}} total tests in shard {shard} of '
                              '{nshards}'.format(total_count - removed, total_count),
                              bold=True, invert=True, yellow=True)
        """.format(shard=sharder.shard, nshards=sharder.nshards))
    except Sharder.InvalidShardSpec as e:
      raise self.InvalidShardSpecification(e)

  def _get_conftest_content(self, sources_map):
    # A conftest hook to modify the console output, replacing the chroot-based
    # source paths with the source-tree based ones, which are more readable to the end user.
    # Note that python stringifies a dict to its source representation, so we can use sources_map
    # as a format argument directly.
    #
    # We'd prefer to hook into pytest_runtest_logstart(), which actually prints the line we
    # want to fix, but we can't because we won't have access to any of its state, so
    # we can't actually change what it prints.
    #
    # Alternatively, we could hook into pytest_collect_file() and just set a custom nodeid
    # for the entire pytest run.  However this interferes with pytest internals, including
    # fixture registration, leading to  fixtures not running when they should.
    # It also requires the generated conftest to be in the root of the source tree, which
    # complicates matters when there's already a user conftest.py there.
    console_output_conftest_content = dedent("""

      ### GENERATED BY PANTS ###

      import pytest

      # Map from source path relative to chroot -> source path relative to buildroot.
      _SOURCES_MAP = {!r}

      @pytest.hookimpl(hookwrapper=True)
      def pytest_runtest_protocol(item, nextitem):
        # Temporarily change the nodeid, which pytest uses for display here.
        real_nodeid = item.nodeid
        real_path = real_nodeid.split('::', 1)[0]
        fixed_path = _SOURCES_MAP.get(real_path, real_path)
        fixed_nodeid = fixed_path + real_nodeid[len(real_path):]
        try:
          item._nodeid = fixed_nodeid
          yield
        finally:
          item._nodeid = real_nodeid
    """.format(dict(sources_map)))
    # Add in the sharding conftest, if any.
    shard_conftest_content = self._get_shard_conftest_content()
    return (console_output_conftest_content + shard_conftest_content).encode('utf8')

  @contextmanager
  def _conftest(self, sources_map):
    """Creates a conftest.py to customize our pytest run."""
    conftest_content = self._get_conftest_content(sources_map)
    # Note that it's important to put the tmpdir under the workdir, because pytest
    # uses all arguments that look like paths to compute its rootdir, and we want
    # it to pick the buildroot.
    with temporary_dir(root_dir=self.workdir) as conftest_dir:
      conftest = os.path.join(conftest_dir, 'conftest.py')
      with open(conftest, 'w') as fp:
        fp.write(conftest_content)
      yield conftest

  @contextmanager
  def _test_runner(self, workdirs, targets, sources_map):
    pex = self.context.products.get_data(PytestPrep.PYTEST_BINARY)
    with self._conftest(sources_map) as conftest:
      with self._maybe_emit_coverage_data(workdirs, targets, pex) as coverage_args:
        yield pex, [conftest] + coverage_args

  def _do_run_tests_with_args(self, pex, args):
    try:
      # The pytest runner we use accepts a --pdb argument that will launch an interactive pdb
      # session on any test failure.  In order to support use of this pass-through flag we must
      # turn off stdin buffering that otherwise occurs.  Setting the PYTHONUNBUFFERED env var to
      # any value achieves this in python2.7.  We'll need a different solution when we support
      # running pants under CPython 3 which does not unbuffer stdin using this trick.
      env = dict(os.environ)
      env['PYTHONUNBUFFERED'] = '1'

      # pytest uses py.io.terminalwriter for output. That class detects the terminal
      # width and attempts to use all of it. However we capture and indent the console
      # output, leading to weird-looking line wraps. So we trick the detection code
      # into thinking the terminal window is narrower than it is.
      env['COLUMNS'] = str(int(os.environ.get('COLUMNS', 80)) - 30)

      profile = self.get_options().profile
      if profile:
        env['PEX_PROFILE_FILENAME'] = '{0}.subprocess.{1:.6f}'.format(profile, time.time())

      with self.context.new_workunit(name='run',
                                     cmd=pex.cmdline(args),
                                     labels=[WorkUnitLabel.TOOL, WorkUnitLabel.TEST]) as workunit:
        rc = self._spawn_and_wait(pex, workunit=workunit, args=args, setsid=True, env=env)
        return PytestResult.rc(rc)
    except ErrorWhileTesting:
      # _spawn_and_wait wraps the test runner in a timeout, so it could
      # fail with a ErrorWhileTesting. We can't just set PythonTestResult
      # to a failure because the resultslog doesn't have all the failures
      # when tests are killed with a timeout. Therefore we need to re-raise
      # here.
      raise
    except Exception:
      self.context.log.error('Failed to run test!')
      self.context.log.info(traceback.format_exc())
      return PytestResult.exception()

  def _map_relsrc_to_targets(self, targets):
    pex_src_root = os.path.relpath(self._source_chroot_path(targets), get_buildroot())
    # First map chrooted sources back to their targets.
    relsrc_to_target = {os.path.join(pex_src_root, src): target for target in targets
      for src in target.sources_relative_to_source_root()}
    # Also map the source tree-rooted sources, because in some cases (e.g., a failure to even
    # eval the test file during test collection), that's the path pytest will use in the junit xml.
    relsrc_to_target.update({src: target for target in targets
      for src in target.sources_relative_to_buildroot()})

    return relsrc_to_target

  def _get_failed_targets_from_junitxml(self, junitxml, targets):
    relsrc_to_target = self._map_relsrc_to_targets(targets)

    # Now find the sources that contained failing tests.
    failed_targets = set()

    try:
      xml = XmlParser.from_file(junitxml)
      failures = int(xml.get_attribute('testsuite', 'failures'))
      errors = int(xml.get_attribute('testsuite', 'errors'))
      if failures or errors:
        for testcase in xml.parsed.getElementsByTagName('testcase'):
          test_failed = testcase.getElementsByTagName('failure')
          test_errored = testcase.getElementsByTagName('error')
          if test_failed or test_errored:
            # The 'file' attribute is a relsrc, because that's what we passed in to pytest.
            failed_targets.add(relsrc_to_target.get(testcase.getAttribute('file')))
    except (XmlParser.XmlError, ValueError) as e:
      raise TaskError('Error parsing xml file at {}: {}'.format(junitxml, e))

    return failed_targets

  def _get_target_from_test(self, test_info, targets):
    relsrc_to_target = self._map_relsrc_to_targets(targets)
    file_info = test_info['file']
    return relsrc_to_target.get(file_info)

  @contextmanager
  def partitions(self, per_target, all_targets, test_targets):
    if per_target:
      def iter_partitions():
        for test_target in test_targets:
          yield (test_target,)
    else:
      targets_by_target_base = OrderedDict()
      for test_target in test_targets:
        targets_for_base = targets_by_target_base.get(test_target.target_base)
        if targets_for_base is None:
          targets_for_base = []
          targets_by_target_base[test_target.target_base] = targets_for_base
        targets_for_base.append(test_target)

      def iter_partitions():
        for test_targets in targets_by_target_base.values():
          yield tuple(test_targets)

    workdir = self.workdir

    def iter_partitions_with_args():
      for partition in iter_partitions():
        workdirs = _Workdirs.for_partition(workdir, partition)
        args = (workdirs,)
        yield partition, args

    yield iter_partitions_with_args

  # TODO(John Sirois): Its probably worth generalizing a means to mark certain options or target
  # attributes as making results un-cacheable. See: https://github.com/pantsbuild/pants/issues/4748
  class NeverCacheFingerprintStrategy(DefaultFingerprintStrategy):
    def compute_fingerprint(self, target):
      return uuid.uuid4()

  def fingerprint_strategy(self):
    if self.get_options().profile:
      # A profile is machine-specific and we assume anyone wanting a profile wants to run it here
      # and now and not accept some old result, even if on the same inputs.
      return self.NeverCacheFingerprintStrategy()
    else:
      return None  # Accept the default fingerprint strategy.

  def run_tests(self, fail_fast, test_targets, workdirs):
    try:
      return self._run_pytest(fail_fast, test_targets, workdirs)
    finally:
      # Unconditionally pluck any results that an end user might need to interact with from the
      # workdir to the locations they expect.
      self._expose_results(test_targets, workdirs)

  def result_from_error(self, error):
    return PytestResult.from_error(error)

  def collect_files(self, workdirs):
    return workdirs.files()

  def _expose_results(self, invalid_tgts, workdirs):
    external_junit_xml_dir = self.get_options().junit_xml_dir
    if external_junit_xml_dir:
      # Either we just ran pytest for a set of invalid targets and generated a junit xml file
      # specific to that (sub)set or else we hit the cache for the whole partition and skipped
      # running pytest, simply retrieving the partition's full junit xml file.
      junitxml_path = workdirs.junitxml_path(*invalid_tgts)

      safe_mkdir(external_junit_xml_dir)
      shutil.copy2(junitxml_path, external_junit_xml_dir)

    if self.get_options().coverage:
      coverage_output_dir = self.get_options().coverage_output_dir
      if coverage_output_dir:
        target_dir = coverage_output_dir
      else:
        pants_distdir = self.context.options.for_global_scope().pants_distdir
        relpath = workdirs.target_set_id()
        target_dir = os.path.join(pants_distdir, 'coverage', relpath)
      mergetree(workdirs.coverage_path, target_dir)

  def _run_pytest(self, fail_fast, targets, workdirs):
    if not targets:
      return PytestResult.rc(0)

    if self.run_tests_in_chroot:
      path_func = lambda rel_src: rel_src
    else:
      source_chroot = os.path.relpath(self._source_chroot_path(targets), get_buildroot())
      path_func = lambda rel_src: os.path.join(source_chroot, rel_src)

    sources_map = OrderedDict()  # Path from chroot -> Path from buildroot.
    for t in targets:
      for p in t.sources_relative_to_source_root():
        sources_map[path_func(p)] = os.path.join(t.target_base, p)

    if not sources_map:
      return PytestResult.rc(0)

    with self._test_runner(workdirs, targets, sources_map) as (pex, test_args):
      # Validate that the user didn't provide any passthru args that conflict
      # with those we must set ourselves.
      for arg in self.get_passthru_args():
        if arg.startswith('--junitxml') or arg.startswith('--confcutdir'):
          raise TaskError('Cannot pass this arg through to pytest: {}'.format(arg))

      junitxml_path = workdirs.junitxml_path(*targets)

      # N.B. the `--confcutdir` here instructs pytest to stop scanning for conftest.py files at the
      # top of the buildroot. This prevents conftest.py files from outside (e.g. in users home dirs)
      # from leaking into pants test runs. See: https://github.com/pantsbuild/pants/issues/2726
      args = ['--junitxml', junitxml_path, '--confcutdir', get_buildroot(),
              '--continue-on-collection-errors']
      if fail_fast:
        args.extend(['-x'])
      if self._debug:
        args.extend(['-s'])
      if self.get_options().colors:
        args.extend(['--color', 'yes'])
      for options in self.get_options().options + self.get_passthru_args():
        args.extend(safe_shlex_split(options))
      args.extend(test_args)
      args.extend(sources_map.keys())

      # We want to ensure our reporting based off junit xml is from this run so kill results from
      # prior runs.
      if os.path.exists(junitxml_path):
        os.unlink(junitxml_path)

      with self._maybe_run_in_chroot(targets):
        result = self._do_run_tests_with_args(pex, args)

      # There was a problem prior to test execution preventing junit xml file creation so just let
      # the failure result bubble.
      if not os.path.exists(junitxml_path):
        return result

      failed_targets = self._get_failed_targets_from_junitxml(junitxml_path, targets)

      def parse_error_handler(parse_error):
        # Simple error handler to pass to xml parsing function.
        raise TaskError('Error parsing xml file at {}: {}'
                        .format(parse_error.xml_path, parse_error.cause))

      all_tests_info = self.parse_test_info(junitxml_path, parse_error_handler,
                                            ['file', 'name', 'classname'])
      for test_name, test_info in all_tests_info.items():
        test_target = self._get_target_from_test(test_info, targets)
        self.report_all_info_for_single_test(self.options_scope, test_target, test_name, test_info)

      return result.with_failed_targets(failed_targets)

  def _source_chroot_path(self, targets):
    if len(targets) > 1:
      target_bases = {target.target_base for target in targets}
      assert len(target_bases) == 1, ('Expected targets to live in the same source root, given '
                                      'targets living under the following source roots: {}'
                                      .format(', '.join(sorted(target_bases))))
    representative_target = targets[0]

    python_sources = self.context.products.get_data(GatherSources.PythonSources)
    return python_sources.for_target(representative_target).path()

  def _pex_run(self, pex, workunit_name, args, env):
    with self.context.new_workunit(name=workunit_name,
                                   cmd=pex.cmdline(args),
                                   labels=[WorkUnitLabel.TOOL, WorkUnitLabel.TEST]) as workunit:
      process = self._spawn(pex, workunit, args, setsid=False, env=env)
      return process.wait()

  @contextmanager
  def _maybe_run_in_chroot(self, targets):
    if self.run_tests_in_chroot:
      with pushd(self._source_chroot_path(targets)):
        yield
    else:
      yield

  def _spawn(self, pex, workunit, args, setsid=False, env=None):
    env = env or {}
    process = pex.run(args,
                      with_chroot=False,  # We handle chrooting ourselves.
                      blocking=False,
                      setsid=setsid,
                      env=env,
                      stdout=workunit.output('stdout'),
                      stderr=workunit.output('stderr'))
    return SubprocessProcessHandler(process)
