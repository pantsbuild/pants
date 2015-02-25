# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import logging
import os
import shutil
import traceback
from contextlib import contextmanager
from textwrap import dedent

from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from six import StringIO
from six.moves import configparser

from pants.backend.python.python_chroot import PythonChroot
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.target import Target
from pants.util.contextutil import environment_as, temporary_dir, temporary_file
from pants.util.dirutil import safe_mkdir, safe_open


# Initialize logging, since tests do not run via pants_exe (where it is usually done)
logging.basicConfig()


class PythonTestResult(object):
  @staticmethod
  def exception():
    return PythonTestResult('EXCEPTION')

  @staticmethod
  def rc(value):
    return PythonTestResult('SUCCESS' if value == 0 else 'FAILURE', rc=value)

  def __init__(self, msg, rc=None):
    self._rc = rc
    self._msg = msg

  def __str__(self):
    return self._msg

  @property
  def success(self):
    return self._rc == 0


class PythonTestBuilder(object):

  _TESTING_TARGETS = [
    PythonRequirement('pytest'),
    PythonRequirement('pytest-timeout'),
    PythonRequirement('pytest-cov'),
    PythonRequirement('unittest2', version_filter=lambda py, pl: py.startswith('2')),
    PythonRequirement('unittest2py3k', version_filter=lambda py, pl: py.startswith('3'))
  ]

  def __init__(self, context, targets, args, interpreter=None, fast=False, debug=False):
    self._context = context
    self._targets = targets
    self._args = args
    self._interpreter = interpreter or PythonInterpreter.get()

    # If fast is true, we run all the tests in a single chroot. This is MUCH faster than
    # creating a chroot for each test target. However running each test separately is more
    # correct, as the isolation verifies that its dependencies are correctly declared.
    self._fast = fast

    self._debug = debug

  def run(self, stdout=None, stderr=None):
    if self._fast:
      return 0 if self._run_tests(self._targets, stdout, stderr).success else 1
    else:
      results = {}
      # Coverage often throws errors despite tests succeeding, so force failsoft in that case.
      fail_hard = ('PANTS_PYTHON_TEST_FAILSOFT' not in os.environ and
                   'PANTS_PY_COVERAGE' not in os.environ)
      for target in self._targets:
        if isinstance(target, PythonTests):
          rv = self._run_tests([target], stdout, stderr)
          results[target.id] = rv
          if not rv.success and fail_hard:
            break
      for target in sorted(results):
        # TODO: Replace print() calls in this file with logging.
        print('%-80s.....%10s' % (target, results[target]), file=stdout)
      return 0 if all(rc.success for rc in results.values()) else 1

  @contextmanager
  def _maybe_emit_junit_xml(self, targets):
    args = []
    xml_base = os.getenv('JUNIT_XML_BASE')
    if xml_base and targets:
      xml_base = os.path.realpath(xml_base)
      xml_path = os.path.join(xml_base, Target.maybe_readable_identify(targets) + '.xml')
      safe_mkdir(os.path.dirname(xml_path))
      args.append('--junitxml=%s' % xml_path)
    yield args

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
        fp.write(dedent('''
          def pytest_configure(__multicall__, config):
            # This executes the rest of the pytest_configures ensuring the `pytest_cov` plugin is
            # registered so we can grab it below.
            __multicall__.execute()
            pycov = config.pluginmanager.getplugin('_cov')
            # Squelch console reporting
            pycov.pytest_terminal_summary = lambda *args, **kwargs: None
        '''))

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
  def _maybe_emit_coverage_data(self, targets, chroot, pex, stdout, stderr):
    coverage = os.environ.get('PANTS_PY_COVERAGE')
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
          # Normalize .coverage.raw paths using combine and `paths` config in the rc file.
          # This swaps the /tmp pex chroot source paths for the local original source paths
          # the pex was generated from and which the user understands.
          shutil.move('.coverage', '.coverage.raw')
          pex.run(args=['combine', '--rcfile', coverage_rc], stdout=stdout, stderr=stderr)

          pex.run(args=['report', '-i', '--rcfile', coverage_rc], stdout=stdout, stderr=stderr)

          # TODO(wickman): If coverage is enabled and we are not using fast mode, write an
          # intermediate .html that points to each of the coverage reports generated and
          # webbrowser.open to that page.
          # TODO(John Sirois): Possibly apply the same logic to the console report.  In fact,
          # consider combining coverage files from all runs in this Tasks's execute and then
          # producing just 1 console and 1 html report whether or not the tests are run in fast
          # mode.
          relpath = Target.maybe_readable_identify(targets)
          pants_distdir = self._context.options.for_global_scope().pants_distdir
          target_dir = os.path.join(pants_distdir, 'coverage', relpath)
          safe_mkdir(target_dir)
          pex.run(args=['html', '-i', '--rcfile', coverage_rc, '-d', target_dir],
                  stdout=stdout, stderr=stderr)
          coverage_xml = os.path.join(target_dir, 'coverage.xml')
          pex.run(args=['xml', '-i', '--rcfile', coverage_rc, '-o', coverage_xml],
                  stdout=stdout, stderr=stderr)

  @contextmanager
  def _test_runner(self, targets, stdout, stderr):
    builder = PEXBuilder(interpreter=self._interpreter)
    builder.info.entry_point = 'pytest'
    chroot = PythonChroot(
      context=self._context,
      targets=targets,
      extra_requirements=self._TESTING_TARGETS,
      builder=builder,
      platforms=('current',),
      interpreter=self._interpreter)
    try:
      builder = chroot.dump()
      builder.freeze()
      pex = PEX(builder.path(), interpreter=self._interpreter)
      with self._maybe_emit_junit_xml(targets) as junit_args:
        with self._maybe_emit_coverage_data(targets,
                                            builder.path(),
                                            pex,
                                            stdout,
                                            stderr) as coverage_args:
          yield pex, junit_args + coverage_args
    finally:
      chroot.delete()

  def _run_tests(self, targets, stdout, stderr):
    if not targets:
      return PythonTestResult.rc(0)

    sources = list(itertools.chain(*[t.sources_relative_to_buildroot() for t in targets]))
    if not sources:
      return PythonTestResult.rc(0)

    with self._test_runner(targets, stdout, stderr) as (pex, test_args):
      args = ['-s'] if self._debug else []
      args.extend(test_args)
      args.extend(self._args)
      args.extend(sources)

      try:
        # The pytest runner we use accepts a --pdb argument that will launch an interactive pdb
        # session on any test failure.  In order to support use of this pass-through flag we must
        # turn off stdin buffering that otherwise occurs.  Setting the PYTHONUNBUFFERED env var to
        # any value achieves this in python2.7.  We'll need a different solution when we support
        # running pants under CPython 3 which does not unbuffer stdin using this trick.
        with environment_as(PYTHONUNBUFFERED='1'):
          rc = pex.run(args=args, setsid=True, stdout=stdout, stderr=stderr)
          return PythonTestResult.rc(rc)
      except Exception:
        print('Failed to run test!', file=stderr)
        traceback.print_exc()
        return PythonTestResult.exception()
