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
from pants.base.exceptions import TaskError, ErrorWhileTesting
from pants.base.hash_utils import Sharder
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.target import Target
from pants.task.testrunner_task_mixin import TestRunnerTaskMixin
from pants.util.contextutil import environment_as, temporary_dir, temporary_file
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
             help='Emit coverage information for specified paths/modules. Value has two forms: '
                  '"module:list,of,modules" or "path:list,of,paths"')
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
        # pytest uses py.io.terminalwriter for output. That class detects the terminal
        # width and attempts to use all of it. However we capture and indent the console
        # output, leading to weird-looking line wraps. So we trick the detection code
        # into thinking the terminal window is narrower than it is.
        cols = os.environ.get('COLUMNS', 80)
        with environment_as(COLUMNS=str(int(cols) - 30)):
          self.run_tests(test_targets, workunit)

  def run_tests(self, targets, workunit):
    result = self._do_run_tests(targets, workunit)
    if not result.success:
      raise ErrorWhileTesting(failed_targets=result.failed_targets)

  class InvalidShardSpecification(TaskError):
    """Indicates an invalid `--test-shard` option."""

  @contextmanager
  def _maybe_shard(self):
    shard_spec = self.get_options().test_shard
    if shard_spec is None:
      yield []
      return

    try:
      sharder = Sharder(shard_spec)

      if sharder.nshards < 2:
        yield []
        return

      # Note that it's important to put the tmpdir under the workdir, because pytest
      # uses all arguments that look like paths to compute its rootdir, and we want
      # it to pick the buildroot.
      with temporary_dir(root_dir=self.workdir) as tmp:
        path = os.path.join(tmp, 'conftest.py')
        with open(path, 'w') as fp:
          fp.write(dedent("""
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
          """.format(shard=sharder.shard, nshards=sharder.nshards)))
        yield [path]
    except Sharder.InvalidShardSpec as e:
      raise self.InvalidShardSpecification(e)

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
  def _cov_setup(self, targets, chroot, coverage_modules=None):
    def compute_coverage_modules(tgt):
      if tgt.coverage:
        return tgt.coverage
      else:
        # This makes the assumption that tests/python/<target> will be testing src/python/<target>.
        # Note in particular that this doesn't work for pants' own tests, as those are under
        # the top level package 'pants_tests', rather than just 'pants'.
        # TODO(John Sirois): consider failing fast if there is no explicit coverage scheme; but also
        # consider supporting configuration of a global scheme whether that be parallel
        # dirs/packages or some arbitrary function that can be registered that takes a test target
        # and hands back the source packages or paths under test.
        return set(os.path.dirname(source).replace(os.sep, '.')
                   for source in tgt.sources_relative_to_source_root())

    if coverage_modules is None:
      coverage_modules = set(itertools.chain(*[compute_coverage_modules(t) for t in targets]))

    def is_python_lib(tgt):
      return tgt.has_sources('.py') and not isinstance(tgt, PythonTests)

    source_mappings = {}
    for target in targets:
      libs = (tgt for tgt in target.closure() if is_python_lib(tgt))
      for lib in libs:
        source_mappings[lib.target_base] = [chroot]

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
      for module in coverage_modules:
        args.extend(['--cov', module])
      yield args, coverage_rc

  @contextmanager
  def _maybe_emit_coverage_data(self, targets, pex, workunit):
    coverage = self.get_options().coverage
    if coverage is None:
      yield []
      return

    def read_coverage_list(prefix):
      return coverage[len(prefix):].split(',')

    pex_src_root = os.path.relpath(
      self.context.products.get_data(GatherSources.PYTHON_SOURCES).path(), get_buildroot())
    coverage_modules = None
    if coverage.startswith('modules:'):
      coverage_modules = read_coverage_list('modules:')
    elif coverage.startswith('paths:'):
      coverage_modules = []
      for path in read_coverage_list('paths:'):
        coverage_modules.append(path)

    with self._cov_setup(targets,
                         pex_src_root,
                         coverage_modules=coverage_modules) as (args, coverage_rc):
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

          # TODO(wickman): If coverage is enabled and we are not using fast mode, write an
          # intermediate .html that points to each of the coverage reports generated and
          # webbrowser.open to that page.
          # TODO(John Sirois): Possibly apply the same logic to the console report.  In fact,
          # consider combining coverage files from all runs in this Tasks's execute and then
          # producing just 1 console and 1 html report whether or not the tests are run in fast
          # mode.
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

  @contextmanager
  def _test_runner(self, targets, workunit):
    pex_info = PexInfo.default()
    pex_info.entry_point = 'pytest'
    pex = self.create_pex(pex_info)

    with self._maybe_shard() as shard_args:
      with self._maybe_emit_coverage_data(targets, pex, workunit) as coverage_args:
        yield pex, shard_args + coverage_args

  def _do_run_tests_with_args(self, pex, workunit, args):
    try:
      # The pytest runner we use accepts a --pdb argument that will launch an interactive pdb
      # session on any test failure.  In order to support use of this pass-through flag we must
      # turn off stdin buffering that otherwise occurs.  Setting the PYTHONUNBUFFERED env var to
      # any value achieves this in python2.7.  We'll need a different solution when we support
      # running pants under CPython 3 which does not unbuffer stdin using this trick.
      # TODO: get rid of all the environment_as() calls in this file and have them modify this
      # env dict directly instead.
      env = dict(os.environ)
      env['PYTHONUNBUFFERED'] = '1'
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

    rel_sources = list(itertools.chain(*[t.sources_relative_to_source_root() for t in targets]))
    if not rel_sources:
      return PythonTestResult.rc(0)
    source_root = os.path.relpath(
      self.context.products.get_data(GatherSources.PYTHON_SOURCES).path(),
      get_buildroot()
    )
    sources = [os.path.join(source_root, p) for p in rel_sources]

    with self._test_runner(targets, workunit) as (pex, test_args):
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
      args.extend(sources)

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
