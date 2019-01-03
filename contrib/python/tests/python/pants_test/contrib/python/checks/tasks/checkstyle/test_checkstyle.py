# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
import re
import sys
from builtins import str
from contextlib import contextmanager
from textwrap import dedent

from pants.backend.python.subsystems.python_repos import PythonRepos
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.build_environment import get_buildroot
from pants.util.collections import assert_single_element
from pants.util.contextutil import environment_as
from pants.util.dirutil import safe_mkdtemp, safe_rmtree
from pants.util.process_handler import subprocess
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase
from parameterized import parameterized
from pex.interpreter import PythonInterpreter
from wheel.install import WheelFile

from pants.contrib.python.checks.tasks.checkstyle.checkstyle import Checkstyle


CHECKER_RESOLVE_METHOD = [('sys.path', True), ('resolve', False)]


class CheckstyleTest(PythonTaskTestBase):

  py2_constraint = 'CPython>=2.7,<3'
  py3_constraint = 'CPython>=3.4,<=3.7'

  @staticmethod
  def build_checker_wheel(root_dir):
    target = Checkstyle._CHECKER_ADDRESS_SPEC
    subprocess.check_call([os.path.join(get_buildroot(), 'pants'),
                           '--pants-distdir={}'.format(root_dir),
                           'setup-py',
                           '--run=bdist_wheel --universal',
                           target])

    for root, _, files in os.walk(root_dir):
      for f in files:
        if f.endswith('.whl'):
          return os.path.join(root, f)

    raise AssertionError('Failed to generate a wheel for {}'.format(target))

  @staticmethod
  def install_wheel(wheel, root_dir):
    importable_path = os.path.join(root_dir, 'install', os.path.basename(wheel))
    overrides = {path: importable_path
                 for path in ('purelib', 'platlib', 'headers', 'scripts', 'data')}
    WheelFile(wheel).install(force=True, overrides=overrides)
    return importable_path

  _distdir = None
  _checker_dist = None
  _checker_dist_importable_path = None

  @classmethod
  def setUpClass(cls):
    cls._distdir = safe_mkdtemp()
    cls._checker_dist = cls.build_checker_wheel(cls._distdir)
    cls._checker_dist_importable_path = cls.install_wheel(cls._checker_dist, cls._distdir)

  @classmethod
  def tearDownClass(cls):
    if cls._distdir:
      safe_rmtree(cls._distdir)

  @classmethod
  def task_type(cls):
    return Checkstyle

  @contextmanager
  def resolve_configuration(self, resolve_local=False):
    if resolve_local:
      # Ensure our checkstyle task runs under the same interpreter we are running under so that
      # local resolves find dists compatible with the current interpreter.
      current_interpreter = PythonInterpreter.get()
      constraint = '{}=={}'.format(current_interpreter.identity.interpreter,
                                   current_interpreter.identity.version_str)
      self.set_options_for_scope(PythonSetup.options_scope, interpreter_constraints=[constraint])

      prior = sys.path[:]
      sys.path.append(self._checker_dist_importable_path)
      try:
        yield
      finally:
        sys.path = prior
    else:
      self.set_options_for_scope(PythonRepos.options_scope,
                                 repos=[os.path.dirname(self._checker_dist)])
      self.set_options_for_scope(PythonSetup.options_scope,
                                 resolver_allow_prereleases=True)
      yield

  def execute_task(self, target_roots=None, resolve_local=False):
    with self.resolve_configuration(resolve_local=resolve_local):
      with environment_as(PANTS_DEV=None, PEX_VERBOSE='9'):
        context = self.context(target_roots=target_roots)
        return self.create_task(context).execute()

  def create_py2_failing_target(self):
    # Has 4 lint errors
    self.create_file('a/python/fail_py2.py', contents=dedent("""
                         x=2+3
                         print x+7
                       """))
    return self.make_target('a/python:fail2', PythonLibrary, sources=['fail_py2.py'],
      compatibility=[self.py2_constraint])

  def create_py3_failing_target(self):
    # Has 3 lint errors
    self.create_file('a/python/fail_py3.py', contents=dedent("""
                         x=2+3
                         print(x+7)
                       """))
    return self.make_target('a/python:fail3', PythonLibrary, sources=['fail_py3.py'],
      compatibility=[self.py3_constraint])

  @parameterized.expand(CHECKER_RESOLVE_METHOD)
  def test_no_sources(self, unused_test_name, resolve_local):
    self.execute_task(resolve_local=resolve_local)

  @parameterized.expand(CHECKER_RESOLVE_METHOD)
  def test_pass(self, unused_test_name, resolve_local):
    self.create_file('a/python/pass.py', contents=dedent("""
                       class UpperCase(object):
                         pass
                     """))
    target = self.make_target('a/python:pass', PythonLibrary, sources=['pass.py'])
    self.set_options(interpreter_constraints_whitelist=[])
    self.execute_task(target_roots=[target], resolve_local=resolve_local)

  @parameterized.expand(CHECKER_RESOLVE_METHOD)
  def test_failure(self, unused_test_name, resolve_local):
    self.create_file('a/python/fail.py', contents=dedent("""
                        class lower_case(object):
                          pass
                       """))
    target = self.make_target('a/python:fail', PythonLibrary, sources=['fail.py'])
    self.set_options(interpreter_constraints_whitelist=[])
    # Needed for when pants runs in a python 3 interpreter.
    with self.assertRaisesRegexp(Checkstyle.CheckstyleRunError,
                                 re.escape('1 Python Style issues found')):
      self.execute_task(target_roots=[target], resolve_local=resolve_local)

  def test_failure_py2_and_py3(self):
    target_py2 = self.create_py2_failing_target()
    target_py3 = self.create_py3_failing_target()
    self.set_options(interpreter_constraints_whitelist=[])
    with self.assertRaises(Checkstyle.CheckstyleRunError) as cm:
      self.execute_task(target_roots=[target_py2, target_py3])
    self.assertIn('7 Python Style issues found', str(cm.exception))
    # Two different interpreters should have been selected.
    self.assertEqual(2, len(cm.exception.failures_by_min_interpreter))
    # One of the interpreters should have been python 3.
    self.assertTrue(cm.exception.py3_was_linted)

  def test_py3_skipped(self):
    target_py3 = self.create_py3_failing_target()
    self.set_options(interpreter_constraints_whitelist=None)
    # The task will succeed (with a deprecation warning), so no exception is raised.
    self.execute_task(target_roots=[target_py3])

  def test_failure_same_interpreter_different_constraints(self):
    target_py2 = self.create_py2_failing_target()
    self.create_file('a/python/fail.py', contents=dedent("""
                        class lower_case(object):
                          pass
                       """))
    target_py2_different = self.make_target(
      'a/python:fail', PythonLibrary, sources=['fail.py'],
      # This will also choose a python 2.7 interpreter, but technically has different filters than
      # self.py2_constraint. Both of these targets should have lint run.
      compatibility=['CPython>=2.7,<2.8'])
    self.set_options(interpreter_constraints_whitelist=[])
    with self.assertRaises(Checkstyle.CheckstyleRunError) as cm:
      self.execute_task(target_roots=[target_py2, target_py2_different])
    self.assertIn('5 Python Style issues found', str(cm.exception))
    # Assert that only a single checker pex was created and invoked, because the same interpreter
    # should have been resolved for both targets.
    self.assertEqual(5, assert_single_element(cm.exception.failures_by_min_interpreter.values()))
    # Assert that there was no python 3-compatible target linted.
    self.assertFalse(cm.exception.py3_was_linted)

  @parameterized.expand(CHECKER_RESOLVE_METHOD)
  def test_suppressed_file_passes(self, unused_test_name, resolve_local):
    self.create_file('a/python/fail.py', contents=dedent("""
                        class lower_case(object):
                          pass
                       """))
    suppression_file = self.create_file('suppress.txt', contents=dedent("""
    a/python/fail\.py::variable-names"""))
    target = self.make_target('a/python:fail', PythonLibrary, sources=['fail.py'])
    self.set_options(suppress=suppression_file, interpreter_constraints_whitelist=[])
    self.execute_task(target_roots=[target], resolve_local=resolve_local)

  @parameterized.expand(CHECKER_RESOLVE_METHOD)
  def test_failure_fail_false(self, unused_test_name, resolve_local):
    self.create_file('a/python/fail.py', contents=dedent("""
                        class lower_case(object):
                          pass
                     """))
    target = self.make_target('a/python:fail', PythonLibrary, sources=['fail.py'])
    self.set_options(fail=False, interpreter_constraints_whitelist=[])
    with self.captured_logging(logging.WARNING) as captured:
      self.execute_task(target_roots=[target], resolve_local=resolve_local)
      self.assertIn('1 Python Style issues found', str(assert_single_element(captured.warnings())))

  @parameterized.expand(CHECKER_RESOLVE_METHOD)
  def test_syntax_error(self, unused_test_name, resolve_local):
    self.create_file('a/python/error.py', contents=dedent("""
                         invalid python
                       """))
    target = self.make_target('a/python:error', PythonLibrary, sources=['error.py'])
    self.set_options(fail=False, interpreter_constraints_whitelist=[])
    with self.captured_logging(logging.WARNING) as captured:
      self.execute_task(target_roots=[target], resolve_local=resolve_local)
      self.assertIn('1 Python Style issues found', str(assert_single_element(captured.warnings())))

  def test_lint_runs_for_default_constraints_only(self):
    target_py2 = self.create_py2_failing_target()
    target_py3 = self.create_py3_failing_target()
    with self.assertRaises(Checkstyle.CheckstyleRunError) as task_error:
      self.execute_task(target_roots=[target_py2, target_py3])
    self.assertIn('4 Python Style issues found', str(task_error.exception))

  def test_lint_ignores_unwhitelisted_constraints(self):
    target_py3 = self.create_py3_failing_target()
    self.execute_task(target_roots=[target_py3])

  def test_lint_runs_for_single_whitelisted_constraints(self):
    target_py3 = self.create_py3_failing_target()
    self.set_options(interpreter_constraints_whitelist=[self.py3_constraint])
    with self.assertRaises(Checkstyle.CheckstyleRunError) as task_error:
      self.execute_task(target_roots=[target_py3])
    self.assertIn('3 Python Style issues found', str(task_error.exception))

  def test_lint_runs_for_multiple_whitelisted_constraints(self):
    target_py2 = self.create_py2_failing_target()
    target_py3 = self.create_py3_failing_target()
    self.set_options(interpreter_constraints_whitelist=[self.py2_constraint, self.py3_constraint])
    with self.assertRaises(Checkstyle.CheckstyleRunError) as task_error:
      self.execute_task(target_roots=[target_py2, target_py3])
    self.assertIn('7 Python Style issues found', str(task_error.exception))

  def test_lint_runs_for_default_constraints_and_matching_whitelist(self):
    target_py2 = self.create_py2_failing_target()
    target_py3 = self.create_py3_failing_target()
    self.set_options(interpreter_constraints_whitelist=[self.py3_constraint])
    with self.assertRaises(Checkstyle.CheckstyleRunError) as task_error:
      self.execute_task(target_roots=[target_py2, target_py3])
    self.assertIn('7 Python Style issues found', str(task_error.exception))
