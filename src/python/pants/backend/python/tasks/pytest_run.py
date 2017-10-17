# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import os
import re
import shutil
import time
import traceback
from contextlib import contextmanager
from textwrap import dedent

from pex.pex_info import PexInfo
from six import StringIO
from six.moves import configparser

from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.python_task import PythonTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import ErrorWhileTesting, TaskError
from pants.base.hash_utils import Sharder
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.target import Target
from pants.task.testrunner_task_mixin import TestRunnerTaskMixin
from pants.util.contextutil import (environment_as, temporary_dir, temporary_file,
                                    temporary_file_path)
from pants.util.dirutil import safe_mkdir, safe_open
from pants.util.process_handler import SubprocessProcessHandler, subprocess
from pants.util.strutil import safe_shlex_split


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


class PytestRun(TestRunnerTaskMixin, PythonTask):
  """
  :API: public
  """

  @classmethod
  def register_options(cls, register):
    super(PytestRun, cls).register_options(register)
    register('--fast', type=bool, default=True,
             help='Run all tests in a single chroot. If turned off, each test target will '
                  'create a new chroot, which will be much slower, but more correct, as the'
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
    if self.get_options().fast:
      result = self._do_run_tests(targets, workunit)
      if not result.success:
        raise ErrorWhileTesting(failed_targets=result.failed_targets)
    else:
      results = {}
      for target in targets:
        rv = self._do_run_tests([target], workunit)
        results[target] = rv
        if not rv.success and self.get_options().fail_fast:
          break

      for target, rv in sorted(results.items()):
        log = self.context.log.info if rv.success else self.context.log.error
        log('{0:80}.....{1:>10}'.format(target.id, rv))

      failed_targets = [target for target, _rv in results.items() if not _rv.success]
      if failed_targets:
        raise ErrorWhileTesting(failed_targets=failed_targets)

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

      with temporary_dir() as tmp:
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

  @contextmanager
  def _maybe_emit_junit_xml(self, targets):
    args = []
    xml_base = self.get_options().junit_xml_dir
    if xml_base and targets:
      xml_base = os.path.realpath(xml_base)
      xml_path = os.path.join(xml_base, Target.maybe_readable_identify(targets) + '.xml')
      safe_mkdir(os.path.dirname(xml_path))
      args.append('--junitxml={}'.format(xml_path))
    yield args

  DEFAULT_COVERAGE_CONFIG = dedent(b"""
    [run]
    branch = True
    timid = True

    [report]
    exclude_lines =
        def __repr__
        raise NotImplementedError
        pragma: no cover
        pragma: no branch
        pragma: recursive coverage
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
    # For the benefit of macos testing, add the 'real' path the directory as an equivalent.
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
    def compute_coverage_modules(target):
      if target.coverage:
        return target.coverage
      else:
        # This makes the assumption that tests/python/<target> will be testing src/python/<target>.
        # Note in particular that this doesn't work for pants' own tests, as those are under
        # the top level package 'pants_tests', rather than just 'pants'.
        # TODO(John Sirois): consider failing fast if there is no explicit coverage scheme; but also
        # consider supporting configuration of a global scheme whether that be parallel
        # dirs/packages or some arbitrary function that can be registered that takes a test target
        # and hands back the source packages or paths under test.
        return set(os.path.dirname(source).replace(os.sep, '.')
                   for source in target.sources_relative_to_source_root())

    if coverage_modules is None:
      coverage_modules = set(itertools.chain(*[compute_coverage_modules(t) for t in targets]))

    # Hack in turning off pytest_cov reporting to the console - we want control this ourselves.
    # Take the approach of registering a plugin that replaces the pycov plugin's
    # `pytest_terminal_summary` callback with a noop.
    with temporary_dir() as plugin_root:
      plugin_root = os.path.realpath(plugin_root)
      with safe_open(os.path.join(plugin_root, 'pants_reporter.py'), 'w') as fp:
        fp.write(dedent("""
          def pytest_configure(__multicall__, config):
            # This executes the rest of the pytest_configures ensuring the `pytest_cov` plugin is
            # registered so we can grab it below.
            __multicall__.execute()
            pycov = config.pluginmanager.getplugin('_cov')
            # Squelch console reporting
            pycov.pytest_terminal_summary = lambda *args, **kwargs: None
        """))

      pythonpath = os.environ.get('PYTHONPATH')
      existing_pythonpath = pythonpath.split(os.pathsep) if pythonpath else []
      with environment_as(PYTHONPATH=os.pathsep.join(existing_pythonpath + [plugin_root])):
        def is_python_lib(tgt):
          return tgt.has_sources('.py') and not isinstance(tgt, PythonTests)

        source_mappings = {}
        for target in targets:
          libs = (tgt for tgt in target.closure() if is_python_lib(tgt))
          for lib in libs:
            source_mappings[lib.target_base] = [chroot]

        cp = self._generate_coverage_config(source_mappings=source_mappings)
        with temporary_file() as fp:
          cp.write(fp)
          fp.close()
          coverage_rc = fp.name
          args = ['-p', 'pants_reporter', '-p', 'pytest_cov', '--cov-config', coverage_rc]
          for module in coverage_modules:
            args.extend(['--cov', module])
          yield args, coverage_rc

  @contextmanager
  def _maybe_emit_coverage_data(self, targets, chroot, pex, workunit):
    coverage = self.get_options().coverage
    if coverage is None:
      yield []
      return

    def read_coverage_list(prefix):
      return coverage[len(prefix):].split(',')

    coverage_modules = None
    if coverage.startswith('modules:'):
      # NB: pytest-cov maps these modules to the `[run] sources` config.  So for
      # `modules:pants.base,pants.util` the config emitted has:
      # [run]
      # source =
      #   pants.base
      #   pants.util
      #
      # Now even though these are not paths, coverage sees the dots and switches to a module
      # prefix-matching mode.  Unfortunately, neither wildcards nor top-level module prefixes
      # like `pants.` serve to engage this module prefix-matching as one might hope.  It
      # appears that `pants.` is treated as a path and `pants.*` is treated as a literal
      # module prefix name.
      coverage_modules = read_coverage_list('modules:')
    elif coverage.startswith('paths:'):
      coverage_modules = []
      for path in read_coverage_list('paths:'):
        if not os.path.exists(path) and not os.path.isabs(path):
          # Look for the source in the PEX chroot since its not available from CWD.
          path = os.path.join(chroot, path)
        coverage_modules.append(path)

    with self._cov_setup(targets,
                         chroot,
                         coverage_modules=coverage_modules) as (args, coverage_rc):
      try:
        yield args
      finally:
        with environment_as(PEX_MODULE='coverage.cmdline:main'):
          def pex_run(args):
            return self._pex_run(pex, workunit, args=args)

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
    interpreter = self.select_interpreter_for_targets(targets)
    pex_info = PexInfo.default()
    pex_info.entry_point = 'pytest'

    # We hard-code the requirements here because they can't be upgraded without
    # major changes to this code, and the PyTest subsystem now contains the versions
    # for the new PytestRun task.  This one is about to be deprecated anyway.
    testing_reqs = [PythonRequirement(s) for s in [
      'pytest>=2.6,<2.7',
      'pytest-timeout<1.0.0',
      'pytest-cov>=1.8,<1.9',
      'unittest2>=0.6.0,<=1.9.0',
    ]]

    chroot = self.cached_chroot(interpreter=interpreter,
                                pex_info=pex_info,
                                targets=targets,
                                platforms=('current',),
                                extra_requirements=testing_reqs)
    pex = chroot.pex()
    with self._maybe_shard() as shard_args:
      with self._maybe_emit_junit_xml(targets) as junit_args:
        with self._maybe_emit_coverage_data(targets,
                                            chroot.path(),
                                            pex,
                                            workunit) as coverage_args:
          yield pex, shard_args + junit_args + coverage_args

  def _do_run_tests_with_args(self, pex, workunit, args):
    try:
      # The pytest runner we use accepts a --pdb argument that will launch an interactive pdb
      # session on any test failure.  In order to support use of this pass-through flag we must
      # turn off stdin buffering that otherwise occurs.  Setting the PYTHONUNBUFFERED env var to
      # any value achieves this in python2.7.  We'll need a different solution when we support
      # running pants under CPython 3 which does not unbuffer stdin using this trick.
      env = {
        'PYTHONUNBUFFERED': '1',
      }
      profile = self.get_options().profile
      if profile:
        env['PEX_PROFILE_FILENAME'] = '{0}.subprocess.{1:.6f}'.format(profile, time.time())
      with environment_as(**env):
        rc = self._spawn_and_wait(pex, workunit, args=args, setsid=True)
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

  # Pattern for lines such as ones below.  The second one is from a test inside a class.
  # F testprojects/tests/python/pants/constants_only/test_fail.py::test_boom
  # F testprojects/tests/python/pants/constants_only/test_fail.py::TestClassName::test_boom


  # If a failure happens outside a function, then the resultlog will have a pattern like this:
  # F testprojects/tests/python/pants/constants_only/test_fail.py

  # 'E' is here as well to catch test errors, not just test failures.
  RESULTLOG_FAILED_PATTERN = re.compile(r'^[EF] +(?P<file>.+?)(::.+)?$')

  @classmethod
  def _get_failed_targets_from_resultlogs(cls, filename, targets):
    with open(filename, 'r') as fp:
      lines = fp.readlines()

    failed_files = {
      m.group('file') for m in map(cls.RESULTLOG_FAILED_PATTERN.match, lines) if m and m.groups()
    }

    failed_targets = set()
    for failed_file in failed_files:
      failed_targets.update(
        t for t in targets if failed_file in t.sources_relative_to_buildroot()
      )

    return list(failed_targets)

  def _do_run_tests(self, targets, workunit):

    def _extract_resultlog_filename(args):
      resultlogs = [arg[arg.find('=') + 1:] for arg in args if arg.startswith('--resultlog=')]
      if resultlogs:
        return resultlogs[0]
      else:
        try:
          return args[args.index('--resultlog') + 1]
        except IndexError:
          self.context.log.error('--resultlog specified without an argument')
          return None
        except ValueError:
          return None

    if not targets:
      return PythonTestResult.rc(0)

    sources = list(itertools.chain(*[t.sources_relative_to_buildroot() for t in targets]))
    if not sources:
      return PythonTestResult.rc(0)

    with self._test_runner(targets, workunit) as (pex, test_args):

      def run_and_analyze(resultlog_path):
        result = self._do_run_tests_with_args(pex, workunit, args)
        failed_targets = self._get_failed_targets_from_resultlogs(resultlog_path, targets)
        return result.with_failed_targets(failed_targets)

      # N.B. the `--confcutdir` here instructs pytest to stop scanning for conftest.py files at the
      # top of the buildroot. This prevents conftest.py files from outside (e.g. in users home dirs)
      # from leaking into pants test runs. See: https://github.com/pantsbuild/pants/issues/2726
      args = ['--confcutdir', get_buildroot()]
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

      # The user might have already specified the resultlog option. In such case, reuse it.
      resultlog_arg = _extract_resultlog_filename(args)

      if resultlog_arg:
        return run_and_analyze(resultlog_arg)
      else:
        with temporary_file_path() as resultlog_path:
          args.insert(0, '--resultlog={0}'.format(resultlog_path))
          return run_and_analyze(resultlog_path)

  def _pex_run(self, pex, workunit, args, setsid=False):
    process = self._spawn(pex, workunit, args, setsid=False)
    return process.wait()

  def _spawn(self, pex, workunit, args, setsid=False):
    # NB: We don't use pex.run(...) here since it makes a point of running in a clean environment,
    # scrubbing all `PEX_*` environment overrides and we use overrides when running pexes in this
    # task.

    process = subprocess.Popen(pex.cmdline(args),
                               preexec_fn=os.setsid if setsid else None,
                               stdout=workunit.output('stdout'),
                               stderr=workunit.output('stderr'))

    return SubprocessProcessHandler(process)
