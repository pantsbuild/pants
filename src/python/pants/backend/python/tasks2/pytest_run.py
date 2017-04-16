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
from contextlib import contextmanager
from textwrap import dedent

from pex.pex_info import PexInfo
from six import StringIO
from six.moves import configparser

from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks2.gather_sources import GatherSources
from pants.backend.python.tasks2.python_execution_task_base import PythonExecutionTaskBase
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import ErrorWhileTesting, TaskError
from pants.base.hash_utils import Sharder
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.target import Target
from pants.task.testrunner_task_mixin import TestRunnerTaskMixin
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_mkdir, safe_mkdir_for
from pants.util.process_handler import SubprocessProcessHandler
from pants.util.strutil import safe_shlex_split
from pants.util.xml_parser import XmlParser


class PythonTestResult(object):
  @staticmethod
  def exception():
    return PythonTestResult('EXCEPTION')

  @staticmethod
  def rc(value):
    return PythonTestResult('SUCCESS' if value == 0 else 'FAILURE', rc=value)

  def with_failed_targets(self, failed_targets):
    return PythonTestResult(self._msg, self._rc, failed_targets)

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


class PytestRun(TestRunnerTaskMixin, PythonExecutionTaskBase):

  @classmethod
  def subsystem_dependencies(cls):
    return super(PytestRun, cls).subsystem_dependencies() + (PyTest,)

  @classmethod
  def register_options(cls, register):
    super(PytestRun, cls).register_options(register)
    register('--fast', type=bool, default=True,
             removal_version='1.5.0.dev0',
             removal_hint='Unused. In the new pipeline tests are always run in "fast" mode.',
             help='Run all tests in a single chroot. If turned off, each test target will '
                  'create a new chroot, which will be much slower, but more correct, as the '
                  'isolation verifies that all dependencies are correctly declared.')
    register('--junit-xml-dir', metavar='<DIR>',
             help='Specifying a directory causes junit xml results files to be emitted under '
                  'that dir for each test run.')
    register('--profile', metavar='<FILE>',
             help="Specifying a file path causes tests to be profiled with the profiling data "
                  "emitted to that file (prefix). Note that tests may run in a different cwd, so "
                  "it's best to use an absolute path to make it easy to find the subprocess "
                  "profiles later.")
    register('--options', type=list, help='Pass these options to pytest.')
    register('--coverage',
             help='Emit coverage information for specified packages or directories (absolute or'
                  'relative to the build root).  The special value "auto" indicates that Pants '
                  'should attempt to deduce which packages to emit coverage for.')
    register('--coverage-output-dir', metavar='<DIR>', default=None,
             help='Directory to emit coverage reports to.'
             'If not specified, a default within dist is used.')
    register('--test-shard',
             help='Subset of tests to run, in the form M/N, 0 <= M < N. For example, 1/3 means '
                  'run tests number 2, 5, 8, 11, ...')

  @classmethod
  def supports_passthru_args(cls):
    return True

  def __init__(self, *args, **kwargs):
    super(PytestRun, self).__init__(*args, **kwargs)

  def extra_requirements(self):
    return PyTest.global_instance().get_requirement_strings()

  def _test_target_filter(self):
    def target_filter(target):
      return isinstance(target, PythonTests)

    return target_filter

  def _validate_target(self, target):
    pass

  def _execute(self, all_targets):
    test_targets = self._get_test_targets()
    if test_targets:
      self.context.release_lock()
      with self.context.new_workunit(name='run',
                                     labels=[WorkUnitLabel.TOOL, WorkUnitLabel.TEST]) as workunit:
        result = self._do_run_tests(test_targets, workunit)
        if not result.success:
          raise ErrorWhileTesting(failed_targets=result.failed_targets)

  class InvalidShardSpecification(TaskError):
    """Indicates an invalid `--test-shard` option."""

  def _get_junit_xml_path(self, targets):
    xml_path = os.path.join(self.workdir, 'junitxml',
                            'TEST-{}.xml'.format(Target.maybe_readable_identify(targets)))
    safe_mkdir_for(xml_path)
    return xml_path

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
    # For the benefit of macos testing, add the 'real' path the the directory as an equivalent.
    def add_realpath(path):
      realpath = os.path.realpath(path)
      if realpath != canonical and realpath not in alternates:
        realpaths.add(realpath)

    cp = configparser.SafeConfigParser()
    cp.readfp(StringIO(self.DEFAULT_COVERAGE_CONFIG))

    # We use the source_mappings to setup the `combine` coverage command to transform paths in
    # coverage data files into canonical form.
    # See the "[paths]" entry here: http://nedbatchelder.com/code/coverage/config.html for details.
    cp.add_section('paths')
    for canonical, alternates in source_mappings.items():
      key = canonical.replace(os.sep, '.')
      realpaths = set()
      add_realpath(canonical)
      for path in alternates:
        add_realpath(path)
      cp.set('paths',
             key,
             self._format_string_list([canonical] + list(alternates) + list(realpaths)))

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
  def _cov_setup(self, source_mappings, coverage_sources=None):
    cp = self._generate_coverage_config(source_mappings=source_mappings)
    # Note that it's important to put the tmpdir under the workdir, because pytest
    # uses all arguments that look like paths to compute its rootdir, and we want
    # it to pick the buildroot.
    with temporary_file(root_dir=self.workdir) as fp:
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
  def _maybe_emit_coverage_data(self, targets, pex, workunit):
    coverage = self.get_options().coverage
    if coverage is None:
      yield []
      return

    pex_src_root = os.path.relpath(
      self.context.products.get_data(GatherSources.PYTHON_SOURCES).path(), get_buildroot())

    source_mappings = {}
    for target in targets:
      libs = (tgt for tgt in target.closure()
              if tgt.has_sources('.py') and not isinstance(tgt, PythonTests))
      for lib in libs:
        source_mappings[lib.target_base] = [pex_src_root]

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
          for target_base in source_mappings:
            prefix = ensure_trailing_sep(target_base)
            if rel_source.startswith(prefix):
              # ... rel_source will match on prefix=src/python/ ...
              suffix = rel_source[len(prefix):]
              # ... suffix will equal foo/bar ...
              coverage_sources.append(os.path.join(pex_src_root, suffix))
              found_target_base = True
              # ... and we end up appending <pex_src_root>/foo/bar to the coverage_sources.
              break
          if not found_target_base:
            self.context.log.warn('Coverage path {} is not in any target. Skipping.'.format(source))
        else:
          # The source is to be interpreted as a package name.
          coverage_sources.append(source)

    with self._cov_setup(source_mappings,
                         coverage_sources=coverage_sources) as (args, coverage_rc):
      try:
        yield args
      finally:
        env = {
          'PEX_MODULE': 'coverage.cmdline:main'
        }
        def pex_run(args):
          return self._pex_run(pex, workunit, args=args, env=env)

        # On failures or timeouts, the .coverage file won't be written.
        if not os.path.exists('.coverage'):
          self.context.log.warn('No .coverage file was found! Skipping coverage reporting.')
        else:
          # Normalize .coverage.raw paths using combine and `paths` config in the rc file.
          # This swaps the /tmp pex chroot source paths for the local original source paths
          # the pex was generated from and which the user understands.
          shutil.move('.coverage', '.coverage.raw')
          pex_run(args=['combine', '--rcfile', coverage_rc])
          pex_run(args=['report', '-i', '--rcfile', coverage_rc])
          if self.get_options().coverage_output_dir:
            target_dir = self.get_options().coverage_output_dir
          else:
            relpath = Target.maybe_readable_identify(targets)
            pants_distdir = self.context.options.for_global_scope().pants_distdir
            target_dir = os.path.join(pants_distdir, 'coverage', relpath)
          safe_mkdir(target_dir)
          pex_run(args=['html', '-i', '--rcfile', coverage_rc, '-d', target_dir])
          coverage_xml = os.path.join(target_dir, 'coverage.xml')
          pex_run(args=['xml', '-i', '--rcfile', coverage_rc, '-o', coverage_xml])

  def _get_shard_conftest_content(self):
    shard_spec = self.get_options().test_shard
    if shard_spec is None:
      return ''

    try:
      sharder = Sharder(shard_spec)
      if sharder.nshards < 2:
        return ''
      return dedent("""
        def pytest_report_header(config):
          return 'shard: {shard} of {nshards} (0-based shard numbering)'

        def pytest_collection_modifyitems(session, config, items):
          total_count = len(items)
          removed = 0
          for i, item in enumerate(list(items)):
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
    console_output_conftest_content = dedent("""

      ### GENERATED BY PANTS ###

      import pytest

      # Map from source path relative to chroot -> source path relative to buildroot.
      _SOURCES_MAP = {}

      @pytest.hookimpl(hookwrapper=True)
      def pytest_collect_file(path, parent):
        outcome = yield
        res = outcome.get_result()
        for module in res:
          # nodeid is used for sorting and display, so it's safe to modify it.
          # Note that module._nodeid is a lazily computed field, while module.nodeid
          # is the property that computes and caches it.
          module._nodeid = _SOURCES_MAP.get(module.nodeid, module.nodeid)
    """.format(sources_map))
    # Add in the sharding conftest, if any.
    shard_conftest_content = self._get_shard_conftest_content()
    return (console_output_conftest_content + shard_conftest_content).encode('utf8')

  @contextmanager
  def _conftest(self, sources_map):
    """Creates a conftest.py to customize our pytest run."""

    conftest_content = self._get_conftest_content(sources_map)
    # We must create our conftest.py in the root of the source chroot, so that its hooks
    # run while loading the test files in that chroot.  We take care not to stomp on an
    # existing conftest.py from the source code.  We temporarily append to it instead.
    conftest = os.path.join(
      self.context.products.get_data(GatherSources.PYTHON_SOURCES).path(), 'conftest.py')
    conftest_orig = None
    # If there's an existing conftest.py, overwrite it to ensure it contains exactly
    # any original user content, plus our temporary additions.
    if os.path.exists(conftest):
      # First, ensure that we've saved the original conftest.py.
      conftest_orig = '{}.orig'.format(conftest)
      if not os.path.exists(conftest_orig):
        # We only copy if the orig file isn't present, to ensure that the conftest.py we're
        # copying is indeed the original one from the source tree, and not one that we
        # created in an earlier run and somehow survived cleanup.
        shutil.copy(conftest, conftest_orig)
      # Here we know that conftest_orig contains the original content, regardless of
      # the state of conftest.
      with open(conftest_orig) as fp:
        orig_conftest_content = fp.read()
      conftest_content = orig_conftest_content + conftest_content

    with open(conftest, 'w') as fp:
      fp.write(conftest_content)
    yield
    # Restore the original state: if there was an original conftest.py, restore
    # its content and remove the conftest_orig file, otherwise delete conftest.py.
    if conftest_orig:
      if os.path.exists(conftest_orig):
        shutil.move(conftest_orig, conftest)
    else:
      os.unlink(conftest)

  @contextmanager
  def _test_runner(self, targets, sources_map, workunit):
    pex_info = PexInfo.default()
    pex_info.entry_point = 'pytest'
    pex = self.create_pex(pex_info)

    with self._conftest(sources_map):
      with self._maybe_emit_coverage_data(targets, pex, workunit) as coverage_args:
        yield pex, [] + coverage_args

  def _do_run_tests_with_args(self, pex, workunit, args):
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
      rc = self._spawn_and_wait(pex, workunit, args=args, setsid=True, env=env)
      return PythonTestResult.rc(rc)
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
      return PythonTestResult.exception()

  def _get_failed_targets_from_junitxml(self, junitxml, targets):
    pex_src_root = os.path.relpath(
      self.context.products.get_data(GatherSources.PYTHON_SOURCES).path(), get_buildroot())
    # First map sources back to their targets.
    relsrc_to_target = {os.path.join(pex_src_root, src): target
                        for target in targets for src in target.sources_relative_to_source_root()}

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

  def _do_run_tests(self, targets, workunit):
    if not targets:
      return PythonTestResult.rc(0)

    buildroot = get_buildroot()
    source_chroot = os.path.relpath(
      self.context.products.get_data(GatherSources.PYTHON_SOURCES).path(), buildroot)
    sources_map = {}  # Path from chroot -> Path from buildroot.
    for t in targets:
      for p in t.sources_relative_to_source_root():
        sources_map[os.path.join(source_chroot, p)] = os.path.join(t.target_base, p)

    if not sources_map:
      return PythonTestResult.rc(0)

    with self._test_runner(targets, sources_map, workunit) as (pex, test_args):
      # Validate that the user didn't provide any passthru args that conflict
      # with those we must set ourselves.
      for arg in self.get_passthru_args():
        if arg.startswith('--junitxml') or arg.startswith('--confcutdir'):
          raise TaskError('Cannot pass this arg through to pytest: {}'.format(arg))

      junitxml_path = self._get_junit_xml_path(targets)
      # N.B. the `--confcutdir` here instructs pytest to stop scanning for conftest.py files at the
      # top of the buildroot. This prevents conftest.py files from outside (e.g. in users home dirs)
      # from leaking into pants test runs. See: https://github.com/pantsbuild/pants/issues/2726
      args = ['--junitxml', junitxml_path, '--confcutdir', get_buildroot(),
              '--continue-on-collection-errors']
      if self.get_options().fail_fast:
        args.extend(['-x'])
      if self._debug:
        args.extend(['-s'])
      if self.get_options().colors:
        args.extend(['--color', 'yes'])
      for options in self.get_options().options + self.get_passthru_args():
        args.extend(safe_shlex_split(options))
      args.extend(test_args)
      args.extend(sources_map.keys())

      result = self._do_run_tests_with_args(pex, workunit, args)
      external_junit_xml_dir = self.get_options().junit_xml_dir
      if external_junit_xml_dir:
        safe_mkdir(external_junit_xml_dir)
        shutil.copy(junitxml_path, external_junit_xml_dir)
      failed_targets = self._get_failed_targets_from_junitxml(junitxml_path, targets)
      return result.with_failed_targets(failed_targets)

  def _pex_run(self, pex, workunit, args, env):
    process = self._spawn(pex, workunit, args, setsid=False, env=env)
    return process.wait()

  def _spawn(self, pex, workunit, args, setsid=False, env=None):
    env = env or {}
    process = pex.run(args, blocking=False, setsid=setsid, env=env,
                      stdout=workunit.output('stdout'), stderr=workunit.output('stderr'))
    return SubprocessProcessHandler(process)
