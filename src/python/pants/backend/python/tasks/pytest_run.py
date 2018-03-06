# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import json
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
from pants.util.contextutil import environment_as, pushd, temporary_dir, temporary_file
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
    return super(PytestRun, cls).implementation_version() + [('PytestRun', 3)]

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
    round_manager.require_data(PytestPrep.PytestBinary)

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
    timid = False

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

  @staticmethod
  def _ensure_section(cp, section):
    if not cp.has_section(section):
      cp.add_section(section)

  # N.B.: Extracted for tests.
  @classmethod
  def _add_plugin_config(cls, cp, src_chroot_path, src_to_target_base):
    # We use a coverage plugin to map PEX chroot source paths back to their original repo paths for
    # report output.
    plugin_module = PytestPrep.PytestBinary.coverage_plugin_module()
    cls._ensure_section(cp, 'run')
    cp.set('run', 'plugins', plugin_module)

    cp.add_section(plugin_module)
    cp.set(plugin_module, 'buildroot', get_buildroot())
    cp.set(plugin_module, 'src_chroot_path', src_chroot_path)
    cp.set(plugin_module, 'src_to_target_base', json.dumps(src_to_target_base))

  def _generate_coverage_config(self, src_to_target_base):
    cp = configparser.SafeConfigParser()
    cp.readfp(StringIO(self.DEFAULT_COVERAGE_CONFIG))

    self._add_plugin_config(cp, self._source_chroot_path, src_to_target_base)

    # See the debug options here: http://nedbatchelder.com/code/coverage/cmd.html#cmd-run-debug
    if self._debug:
      debug_options = self._format_string_list([
        # Dumps the coverage config realized values.
        'config',
        # Logs which files are skipped or traced and why.
        'trace'])
      self._ensure_section(cp, 'run')
      cp.set('run', 'debug', debug_options)

    return cp

  @staticmethod
  def _is_coverage_env_var(name):
    return (
      name.startswith('COV_CORE_')  # These are from `pytest-cov`.
      or name.startswith('COVERAGE_')  # These are from `coverage`.
    )

  @contextmanager
  def _scrub_cov_env_vars(self):
    cov_env_vars = {k: v for k, v in os.environ.items() if self._is_coverage_env_var(k)}
    if cov_env_vars:
      self.context.log.warn('Scrubbing coverage environment variables\n\t{}'
                            .format('\n\t'.join(sorted('{}={}'.format(k, v)
                                                       for k, v in cov_env_vars.items()))))
      with environment_as(**{k: None for k in cov_env_vars}):
        yield
    else:
      yield

  @contextmanager
  def _cov_setup(self, workdirs, coverage_morfs, src_to_target_base):
    cp = self._generate_coverage_config(src_to_target_base=src_to_target_base)
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
      for morf in coverage_morfs:
        args.extend(['--cov', morf])

      with self._scrub_cov_env_vars():
        yield args, coverage_rc

  @contextmanager
  def _maybe_emit_coverage_data(self, workdirs, test_targets, pex):
    coverage = self.get_options().coverage
    if coverage is None:
      yield []
      return

    pex_src_root = os.path.relpath(self._source_chroot_path, get_buildroot())

    src_to_target_base = {}
    for target in test_targets:
      libs = (tgt for tgt in target.closure()
              if tgt.has_sources('.py') and not isinstance(tgt, PythonTests))
      for lib in libs:
        for src in lib.sources_relative_to_source_root():
          src_to_target_base[src] = lib.target_base

    def ensure_trailing_sep(path):
      return path if path.endswith(os.path.sep) else path + os.path.sep

    if coverage == 'auto':
      def compute_coverage_pkgs(tgt):
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
          def package(test_source_path):
            return os.path.dirname(test_source_path).replace(os.sep, '.')

          def packages():
            for test_source_path in tgt.sources_relative_to_source_root():
              pkg = package(test_source_path)
              if pkg:
                yield pkg

          return packages()

      coverage_morfs = set(itertools.chain(*[compute_coverage_pkgs(t) for t in test_targets]))
    else:
      coverage_morfs = []
      for morf in coverage.split(','):
        if os.path.isdir(morf):
          # The source is a dir, so correct its prefix for the chroot.
          # E.g. if source is /path/to/src/python/foo/bar or src/python/foo/bar then
          # rel_source is src/python/foo/bar, and ...
          rel_source = os.path.relpath(morf, get_buildroot())
          rel_source = ensure_trailing_sep(rel_source)

          found_target_base = False
          for target_base in set(src_to_target_base.values()):
            prefix = ensure_trailing_sep(target_base)
            if rel_source.startswith(prefix):
              # ... rel_source will match on prefix=src/python/ ...
              suffix = rel_source[len(prefix):]
              # ... suffix will equal foo/bar ...
              coverage_morfs.append(os.path.join(get_buildroot(), pex_src_root, suffix))
              found_target_base = True
              # ... and we end up appending <pex_src_root>/foo/bar to the coverage_sources.
              break
          if not found_target_base:
            self.context.log.warn('Coverage path {} is not in any target. Skipping.'.format(morf))
        else:
          # The source is to be interpreted as a package name.
          coverage_morfs.append(morf)

    with self._cov_setup(workdirs,
                         coverage_morfs=coverage_morfs,
                         src_to_target_base=src_to_target_base) as (args, coverage_rc):
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

        # The '.coverage' data file is output in the CWD of the test run above; so we make sure to
        # look for it there.
        with self._maybe_run_in_chroot():
          # On failures or timeouts, the .coverage file won't be written.
          if not os.path.exists('.coverage'):
            self.context.log.warn('No .coverage file was found! Skipping coverage reporting.')
          else:
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

  def _get_conftest_content(self, sources_map, rootdir_comm_path):
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

      import os

      import pytest


      class NodeRenamerPlugin(object):
        # Map from absolute source chroot path -> path of original source relative to the buildroot.
        _SOURCES_MAP = {sources_map!r}

        def __init__(self, rootdir):
          def rootdir_relative(path):
            return os.path.relpath(path, rootdir)

          self._sources_map = {{rootdir_relative(k): rootdir_relative(v)
                                for k, v in self._SOURCES_MAP.items()}}

        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_protocol(self, item, nextitem):
          # Temporarily change the nodeid, which pytest uses for display.
          real_nodeid = item.nodeid
          real_path = real_nodeid.split('::', 1)[0]
          fixed_path = self._sources_map.get(real_path, real_path)
          fixed_nodeid = fixed_path + real_nodeid[len(real_path):]
          try:
            item._nodeid = fixed_nodeid
            yield
          finally:
            item._nodeid = real_nodeid


      # The path to write out the py.test rootdir to.
      _ROOTDIR_COMM_PATH = {rootdir_comm_path!r}


      def pytest_configure(config):
        rootdir = str(config.rootdir)
        with open(_ROOTDIR_COMM_PATH, 'w') as fp:
          fp.write(rootdir)

        config.pluginmanager.register(NodeRenamerPlugin(rootdir), 'pants_test_renamer')

    """.format(sources_map=dict(sources_map), rootdir_comm_path=rootdir_comm_path))
    # Add in the sharding conftest, if any.
    shard_conftest_content = self._get_shard_conftest_content()
    return (console_output_conftest_content + shard_conftest_content).encode('utf8')

  @contextmanager
  def _conftest(self, sources_map):
    """Creates a conftest.py to customize our pytest run."""
    # Note that it's important to put the tmpdir under the workdir, because pytest
    # uses all arguments that look like paths to compute its rootdir, and we want
    # it to pick the buildroot.
    with temporary_dir(root_dir=self.workdir) as conftest_dir:
      rootdir_comm_path = os.path.join(conftest_dir, 'pytest_rootdir.path')

      def get_pytest_rootdir():
        with open(rootdir_comm_path, 'r') as fp:
          return fp.read()

      conftest_content = self._get_conftest_content(sources_map,
                                                    rootdir_comm_path=rootdir_comm_path)

      conftest = os.path.join(conftest_dir, 'conftest.py')
      with open(conftest, 'w') as fp:
        fp.write(conftest_content)
      yield conftest, get_pytest_rootdir

  @contextmanager
  def _test_runner(self, workdirs, test_targets, sources_map):
    pytest_binary = self.context.products.get_data(PytestPrep.PytestBinary)
    with self._conftest(sources_map) as (conftest, get_pytest_rootdir):
      with self._maybe_emit_coverage_data(workdirs,
                                          test_targets,
                                          pytest_binary.pex) as coverage_args:
        yield pytest_binary, [conftest] + coverage_args, get_pytest_rootdir

  def _do_run_tests_with_args(self, pex, args):
    try:
      env = dict(os.environ)

      # Ensure we don't leak source files or undeclared 3rdparty requirements into the py.test PEX
      # environment.
      pythonpath = env.pop('PYTHONPATH', None)
      if pythonpath:
        self.context.log.warn('scrubbed PYTHONPATH={} from py.test environment'.format(pythonpath))

      # The pytest runner we use accepts a --pdb argument that will launch an interactive pdb
      # session on any test failure.  In order to support use of this pass-through flag we must
      # turn off stdin buffering that otherwise occurs.  Setting the PYTHONUNBUFFERED env var to
      # any value achieves this in python2.7.  We'll need a different solution when we support
      # running pants under CPython 3 which does not unbuffer stdin using this trick.
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
    pex_src_root = os.path.relpath(self._source_chroot_path, get_buildroot())
    # First map chrooted sources back to their targets.
    relsrc_to_target = {os.path.join(pex_src_root, src): target for target in targets
      for src in target.sources_relative_to_source_root()}
    # Also map the source tree-rooted sources, because in some cases (e.g., a failure to even
    # eval the test file during test collection), that's the path pytest will use in the junit xml.
    relsrc_to_target.update({src: target for target in targets
      for src in target.sources_relative_to_buildroot()})

    return relsrc_to_target

  def _get_failed_targets_from_junitxml(self, junitxml, targets, pytest_rootdir):
    relsrc_to_target = self._map_relsrc_to_targets(targets)
    buildroot_relpath = os.path.relpath(pytest_rootdir, get_buildroot())

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
            # The file attribute is always relative to the py.test rootdir.
            pytest_relpath = testcase.getAttribute('file')
            relsrc = os.path.join(buildroot_relpath, pytest_relpath)
            failed_target = relsrc_to_target.get(relsrc)
            failed_targets.add(failed_target)
    except (XmlParser.XmlError, ValueError) as e:
      raise TaskError('Error parsing xml file at {}: {}'.format(junitxml, e))

    return failed_targets

  def _get_target_from_test(self, test_info, targets, pytest_rootdir):
    relsrc_to_target = self._map_relsrc_to_targets(targets)
    buildroot_relpath = os.path.relpath(pytest_rootdir, get_buildroot())
    pytest_relpath = test_info['file']
    relsrc = os.path.join(buildroot_relpath, pytest_relpath)
    return relsrc_to_target.get(relsrc)

  @contextmanager
  def partitions(self, per_target, all_targets, test_targets):
    if per_target:
      def iter_partitions():
        for test_target in test_targets:
          yield (test_target,)
    else:
      def iter_partitions():
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
      return self._run_pytest(fail_fast, tuple(test_targets), workdirs)
    finally:
      # Unconditionally pluck any results that an end user might need to interact with from the
      # workdir to the locations they expect.
      self._expose_results(test_targets, workdirs)

  @memoized_property
  def result_class(self):
    return PytestResult

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

  def _run_pytest(self, fail_fast, test_targets, workdirs):
    if not test_targets:
      return PytestResult.rc(0)

    # Absolute path to chrooted test file -> Path to original test file relative to the buildroot.
    sources_map = OrderedDict()
    for t in test_targets:
      for p in t.sources_relative_to_source_root():
        sources_map[os.path.join(self._source_chroot_path, p)] = os.path.join(t.target_base, p)

    if not sources_map:
      return PytestResult.rc(0)

    with self._test_runner(workdirs, test_targets, sources_map) as (pytest_binary,
                                                                    test_args,
                                                                    get_pytest_rootdir):
      # Validate that the user didn't provide any passthru args that conflict
      # with those we must set ourselves.
      for arg in self.get_passthru_args():
        if arg.startswith('--junitxml') or arg.startswith('--confcutdir'):
          raise TaskError('Cannot pass this arg through to pytest: {}'.format(arg))

      junitxml_path = workdirs.junitxml_path(*test_targets)

      # N.B. the `--confcutdir` here instructs pytest to stop scanning for conftest.py files at the
      # top of the buildroot. This prevents conftest.py files from outside (e.g. in users home dirs)
      # from leaking into pants test runs. See: https://github.com/pantsbuild/pants/issues/2726
      args = ['-c', pytest_binary.config_path,
              '--junitxml', junitxml_path,
              '--confcutdir', get_buildroot(),
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

      with self._maybe_run_in_chroot():
        result = self._do_run_tests_with_args(pytest_binary.pex, args)

      # There was a problem prior to test execution preventing junit xml file creation so just let
      # the failure result bubble.
      if not os.path.exists(junitxml_path):
        return result

      pytest_rootdir = get_pytest_rootdir()
      failed_targets = self._get_failed_targets_from_junitxml(junitxml_path,
                                                              test_targets,
                                                              pytest_rootdir)

      def parse_error_handler(parse_error):
        # Simple error handler to pass to xml parsing function.
        raise TaskError('Error parsing xml file at {}: {}'
                        .format(parse_error.xml_path, parse_error.cause))

      all_tests_info = self.parse_test_info(junitxml_path, parse_error_handler,
                                            ['file', 'name', 'classname'])
      for test_name, test_info in all_tests_info.items():
        test_target = self._get_target_from_test(test_info, test_targets, pytest_rootdir)
        self.report_all_info_for_single_test(self.options_scope, test_target, test_name, test_info)

      return result.with_failed_targets(failed_targets)

  @memoized_property
  def _source_chroot_path(self):
    return self.context.products.get_data(GatherSources.PYTHON_SOURCES).path()

  def _pex_run(self, pex, workunit_name, args, env):
    with self.context.new_workunit(name=workunit_name,
                                   cmd=pex.cmdline(args),
                                   labels=[WorkUnitLabel.TOOL, WorkUnitLabel.TEST]) as workunit:
      process = self._spawn(pex, workunit, args, setsid=False, env=env)
      return process.wait()

  @contextmanager
  def _maybe_run_in_chroot(self):
    if self.run_tests_in_chroot:
      with pushd(self._source_chroot_path):
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
