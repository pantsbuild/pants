# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

from __future__ import print_function

__author__ = 'Brian Wickman'

try:
  import configparser
except ImportError:
  import ConfigParser as configparser
import errno
import os
import time
import signal
import sys

from twitter.common.collections import OrderedSet
from twitter.common.contextutil import temporary_file
from twitter.common.dirutil import safe_mkdir
from twitter.common.lang import Compatibility
from twitter.common.quantity import Amount, Time
from twitter.common.python.pex import PEX
from twitter.common.python.pex_builder import PEXBuilder

from twitter.pants.base import Config, ParseContext
from twitter.pants.python.python_chroot import PythonChroot
from twitter.pants.targets import (
    PythonRequirement,
    PythonTarget,
    PythonTestSuite,
    PythonTests)


class PythonTestResult(object):
  @staticmethod
  def timeout():
    return PythonTestResult('TIMEOUT')

  @staticmethod
  def exception():
    return PythonTestResult('EXCEPTION')

  @staticmethod
  def rc(value):
    return PythonTestResult('SUCCESS' if value == 0 else 'FAILURE',
                            rc=value)

  def __init__(self, msg, rc=None):
    self._rc = rc
    self._msg = msg

  def __str__(self):
    return self._msg

  @property
  def success(self):
    return self._rc == 0


DEFAULT_COVERAGE_CONFIG = """
[run]
branch = True
timid = True

[report]
exclude_lines =
    def __repr__
    raise NotImplementedError

ignore_errors = True
"""

def generate_coverage_config(target):
  cp = configparser.ConfigParser()
  cp.readfp(Compatibility.StringIO(DEFAULT_COVERAGE_CONFIG))
  cp.add_section('html')
  target_dir = os.path.join(Config.load().getdefault('pants_distdir'), 'coverage',
      os.path.dirname(target.address.buildfile.relpath), target.name)
  safe_mkdir(target_dir)
  cp.set('html', 'directory', target_dir)
  return cp


class PythonTestBuilder(object):
  class InvalidDependencyException(Exception): pass
  class ChrootBuildingException(Exception): pass
  TESTING_TARGETS = None

  # TODO(wickman) Expose these as configuratable parameters
  TEST_TIMEOUT = Amount(2, Time.MINUTES)
  TEST_POLL_PERIOD = Amount(100, Time.MILLISECONDS)

  def __init__(self, targets, args, root_dir, conn_timeout=None):
    self.targets = targets
    self.args = args
    self.root_dir = root_dir
    self.successes = {}
    self._conn_timeout = conn_timeout

  def run(self):
    self.successes = {}
    rv = self._run_tests(self.targets)
    for target in sorted(self.successes):
      print('%-80s.....%10s' % (target, self.successes[target]))
    return 0 if rv.success else 1

  @classmethod
  def generate_test_targets(cls):
    if cls.TESTING_TARGETS is None:
      with ParseContext.temp():
        cls.TESTING_TARGETS = [
          PythonRequirement('pytest'),
          PythonRequirement('pytest-cov'),
          PythonRequirement('coverage==3.6b1'),
          PythonRequirement('unittest2', version_filter=lambda py, pl: py.startswith('2')),
          PythonRequirement('unittest2py3k', version_filter=lambda py, pl: py.startswith('3'))
        ]
    return cls.TESTING_TARGETS

  @staticmethod
  def generate_junit_args(target):
    args = []
    xml_base = os.getenv('JUNIT_XML_BASE')
    if xml_base:
      xml_base = os.path.abspath(os.path.normpath(xml_base))
      xml_path = os.path.join(
        xml_base, os.path.dirname(target.address.buildfile.relpath), target.name + '.xml')
      try:
        os.makedirs(os.path.dirname(xml_path))
      except OSError as e:
        if e.errno != errno.EEXIST:
          raise PythonTestBuilder.ChrootBuildingException(
            "Unable to establish JUnit target: %s!  %s" % (target, e))
      args.append('--junitxml=%s' % xml_path)
    return args

  @staticmethod
  def cov_setup(target, chroot):
    cp = generate_coverage_config(target)
    with temporary_file(cleanup=False) as fp:
      cp.write(fp)
      filename = fp.name
    if target.coverage:
      source = target.coverage
    else:
      # This technically makes the assumption that tests/python/<target> will be testing
      # src/python/<target>.  To change to honest measurements, do target.walk() here insead,
      # however this results in very useless and noisy coverage reports.
      source = set(os.path.dirname(source).replace(os.sep, '.') for source in target.sources)
    args = ['-p', 'pytest_cov',
            '--cov-config', filename,
            '--cov-report', 'html',
            '--cov-report', 'term']
    for module in source:
      args.extend(['--cov', module])
    return filename, args

  @staticmethod
  def wait_on(popen, timeout=TEST_TIMEOUT):
    total_wait = Amount(0, Time.SECONDS)
    while total_wait < timeout:
      rc = popen.poll()
      if rc is not None:
        return PythonTestResult.rc(rc)
      total_wait += PythonTestBuilder.TEST_POLL_PERIOD
      time.sleep(PythonTestBuilder.TEST_POLL_PERIOD.as_(Time.SECONDS))
    popen.kill()
    return PythonTestResult.timeout()

  def _run_python_test(self, target):
    po = None
    rv = PythonTestResult.exception()
    coverage_rc = None
    coverage_enabled = 'PANTS_PY_COVERAGE' in os.environ

    try:
      builder = PEXBuilder()
      builder.info.entry_point = target.entry_point
      builder.info.ignore_errors = target._soft_dependencies
      chroot = PythonChroot(target, self.root_dir, extra_targets=self.generate_test_targets(),
                            builder=builder, conn_timeout=self._conn_timeout)
      builder = chroot.dump()
      builder.freeze()
      test_args = PythonTestBuilder.generate_junit_args(target)
      test_args.extend(self.args)
      if coverage_enabled:
        coverage_rc, args = self.cov_setup(target, builder.chroot())
        test_args.extend(args)
      sources = [os.path.join(target.target_base, source) for source in target.sources]
      po = PEX(builder.path()).run(args=test_args + sources, blocking=False, setsid=True)
      # TODO(wickman)  If coverage is enabled, write an intermediate .html that points to
      # each of the coverage reports generated and webbrowser.open to that page.
      rv = PythonTestBuilder.wait_on(po, timeout=target.timeout)
    except Exception as e:
      import traceback
      print('Failed to run test!', file=sys.stderr)
      traceback.print_exc()
      rv = PythonTestResult.exception()
    finally:
      if coverage_rc:
        os.unlink(coverage_rc)
      if po and po.returncode != 0:
        try:
          os.killpg(po.pid, signal.SIGTERM)
        except OSError as e:
          if e.errno == errno.EPERM:
            print("Unable to kill process group: %d" % po.pid)
          elif e.errno != errno.ESRCH:
            rv = PythonTestResult.exception()
    self.successes[target._create_id()] = rv
    return rv

  def _run_python_test_suite(self, target, fail_hard=True):
    tests = OrderedSet([])
    def _gather_deps(trg):
      if isinstance(trg, PythonTests):
        tests.add(trg)
      elif isinstance(trg, PythonTestSuite):
        for dependency in trg.dependencies:
          for dep in dependency.resolve():
            _gather_deps(dep)
    _gather_deps(target)

    failed = False
    for test in tests:
      rv = self._run_python_test(test)
      if not rv.success:
        failed = True
        if fail_hard:
          return rv
    return PythonTestResult.rc(1 if failed else 0)

  def _run_tests(self, targets):
    fail_hard = 'PANTS_PYTHON_TEST_FAILSOFT' not in os.environ
    if 'PANTS_PY_COVERAGE' in os.environ:
      # Coverage often throws errors despite tests succeeding, so make PANTS_PY_COVERAGE
      # force FAILSOFT.
      fail_hard = False
    failed = False
    for target in targets:
      if isinstance(target, PythonTests):
        rv = self._run_python_test(target)
      elif isinstance(target, PythonTestSuite):
        rv = self._run_python_test_suite(target, fail_hard)
      else:
        raise PythonTestBuilder.InvalidDependencyException(
          "Invalid dependency in python test target: %s" % target)
      if not rv.success:
        failed = True
        if fail_hard:
          return rv
    return PythonTestResult.rc(1 if failed else 0)
