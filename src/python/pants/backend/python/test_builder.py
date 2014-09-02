# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

try:
  import configparser
except ImportError:
  import ConfigParser as configparser
import itertools
import os

from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from twitter.common.lang import Compatibility

from pants.backend.python.python_chroot import PythonChroot
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.config import Config
from pants.base.target import Target
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_mkdir


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


DEFAULT_COVERAGE_CONFIG = b"""
[run]
branch = True
timid = True

;NB: The debug config below is useful when debugging coverage issues.
;debug =
;  config
;  trace

[report]
exclude_lines =
    def __repr__
    raise NotImplementedError

ignore_errors = True
"""


def generate_coverage_config(targets):
  cp = configparser.ConfigParser()
  cp.readfp(Compatibility.StringIO(DEFAULT_COVERAGE_CONFIG))
  cp.add_section('html')
  if len(targets) == 1:
    target = targets[0]
    relpath = os.path.join(os.path.dirname(target.address.build_file.relpath), target.name)
  else:
    relpath = Target.maybe_readable_identify(targets)
  target_dir = os.path.join(Config.load().getdefault('pants_distdir'), 'coverage', relpath)
  safe_mkdir(target_dir)
  cp.set('html', 'directory', target_dir)
  return cp


class PythonTestBuilder(object):
  class InvalidDependencyException(Exception): pass
  class ChrootBuildingException(Exception): pass

  _TESTING_TARGETS = [
    PythonRequirement('pytest'),
    PythonRequirement('pytest-timeout'),
    PythonRequirement('pytest-cov'),
    PythonRequirement('unittest2', version_filter=lambda py, pl: py.startswith('2')),
    PythonRequirement('unittest2py3k', version_filter=lambda py, pl: py.startswith('3'))
  ]

  def __init__(self, targets, args, interpreter=None, conn_timeout=None, fast=False):
    self.targets = targets
    self.args = args
    self.interpreter = interpreter or PythonInterpreter.get()
    self._conn_timeout = conn_timeout

    # If fast is true, we run all the tests in a single chroot. This is MUCH faster than
    # creating a chroot for each test target. However running each test separately is more
    # correct, as the isolation verifies that its dependencies are correctly declared.
    self._fast = fast

  def run(self, stdout=None, stderr=None):
    if self._fast:
      return 0 if self._run_python_tests(self.targets, stdout, stderr).success else 1
    else:
      results = {}
      # Coverage often throws errors despite tests succeeding, so force failsoft in that case.
      fail_hard = ('PANTS_PYTHON_TEST_FAILSOFT' not in os.environ and
                   'PANTS_PY_COVERAGE' not in os.environ)
      for target in self.targets:
        if isinstance(target, PythonTests):
          rv = self._run_python_tests([target], stdout, stderr)
          results[target.id] = rv
          if not rv.success and fail_hard:
            break
      for target in sorted(results):
        # TODO: Replace print() calls in this file with logging.
        print('%-80s.....%10s' % (target, results[target]), file=stdout)
      return 0 if all(rc.success for rc in results.values()) else 1

  @staticmethod
  def generate_junit_args(targets):
    args = []
    xml_base = os.getenv('JUNIT_XML_BASE')
    if xml_base and targets:
      xml_base = os.path.abspath(os.path.normpath(xml_base))
      if len(targets) == 1:
        target = targets[0]
        relpath = os.path.join(os.path.dirname(target.address.build_file.relpath),
                               target.name + '.xml')
      else:
        relpath = Target.maybe_readable_identify(targets) + '.xml'
      xml_path = os.path.join(xml_base, relpath)
      safe_mkdir(os.path.dirname(xml_path))
      args.append('--junitxml=%s' % xml_path)
    return args

  @staticmethod
  def cov_setup(targets, coverage_modules=None):
    cp = generate_coverage_config(targets)
    with temporary_file(cleanup=False) as fp:
      cp.write(fp)
      filename = fp.name

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
    args = ['-p', 'pytest_cov',
            '--cov-config', filename,
            '--cov-report', 'html',
            '--cov-report', 'term']
    for module in coverage_modules:
      args.extend(['--cov', module])
    return filename, args

  def _run_python_tests(self, targets, stdout, stderr):
    coverage_rc = None

    try:
      builder = PEXBuilder(interpreter=self.interpreter)
      builder.info.entry_point = 'pytest'
      chroot = PythonChroot(
          targets=targets,
          extra_requirements=self._TESTING_TARGETS,
          builder=builder,
          platforms=('current',),
          interpreter=self.interpreter,
          conn_timeout=self._conn_timeout)
      builder = chroot.dump()
      builder.freeze()
      test_args = []
      test_args.extend(PythonTestBuilder.generate_junit_args(targets))
      test_args.extend(self.args)

      coverage_modules = None
      coverage = os.environ.get('PANTS_PY_COVERAGE')
      if coverage is not None:
        def read_coverage_list(prefix):
          return coverage[len(prefix):].split(',')

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
          # like `pants.` serve to engage this module prefix-matching as one might hope.  It appears
          # that `pants.` is treated as a path and `pants.*` is treated as a literal module prefix
          # name.
          coverage_modules = read_coverage_list('modules:')
        elif coverage.startswith('paths:'):
          coverage_modules = []
          for path in read_coverage_list('paths:'):
            if os.path.isfile(path):
              raise ValueError('Coverage paths cannot be files, they can only be dirs. '
                               'Given file {0}'.format(path))
            if not os.path.exists(path) and not os.path.isabs(path):
              # Look for the source in the PEX chroot since its not available from CWD.
              path = os.path.join(builder.path(), path)
            coverage_modules.append(path)

        coverage_rc, args = self.cov_setup(targets, coverage_modules=coverage_modules)
        test_args.extend(args)

      sources = list(itertools.chain(*[t.sources_relative_to_buildroot() for t in targets]))
      pex = PEX(builder.path(), interpreter=self.interpreter)
      rc = pex.run(args=test_args + sources, blocking=True, setsid=True,
                   stdout=stdout, stderr=stderr)
      # TODO(wickman): If coverage is enabled, write an intermediate .html that points to
      # each of the coverage reports generated and webbrowser.open to that page.
      rv = PythonTestResult.rc(rc)
    except Exception:
      import traceback
      print('Failed to run test!', file=stderr)
      traceback.print_exc()
      rv = PythonTestResult.exception()
    finally:
      if coverage_rc:
        os.unlink(coverage_rc)
    return rv
