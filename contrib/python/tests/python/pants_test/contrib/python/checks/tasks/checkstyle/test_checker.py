# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import str
from textwrap import dedent

from pants.backend.python.subsystems.python_repos import PythonRepos
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.util.contextutil import environment_as
from pants.util.dirutil import safe_mkdtemp, safe_rmtree
from pants.util.process_handler import subprocess
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase

from pants.contrib.python.checks.tasks.checkstyle.checkstyle import Checkstyle


class CheckstyleTest(PythonTaskTestBase):

  _distdir = None
  _checker_dist = None

  @classmethod
  def setUpClass(cls):
    cls._distdir = safe_mkdtemp()
    target = Checkstyle._CHECKER_ADDRESS_SPEC
    subprocess.check_call([os.path.join(get_buildroot(), 'pants'),
                           '--pants-distdir={}'.format(cls._distdir),
                           'setup-py',
                           '--run=bdist_wheel --universal',
                           target])

    for root, dirs, files in os.walk(cls._distdir):
      for f in files:
        if f.endswith('.whl'):
          cls._checker_dist = os.path.join(root, f)
          break
    if cls._checker_dist is None:
      raise AssertionError('Failed to generate a wheel for {}'.format(target))

  @classmethod
  def tearDownClass(cls):
    if cls._distdir:
      safe_rmtree(cls._distdir)

  @classmethod
  def task_type(cls):
    return Checkstyle

  def execute_task(self, target_roots=None):
    with environment_as(PANTS_DEV=None, PEX_VERBOSE='9'):
      self.set_options_for_scope(PythonRepos.options_scope,
                                 repos=[os.path.dirname(self._checker_dist)])
      self.set_options_for_scope(PythonSetup.options_scope,
                                 resolver_allow_prereleases=True)
      context = self.context(target_roots=target_roots)
      return self.create_task(context).execute()

  def test_no_sources(self):
    self.assertEqual(None, self.execute_task())

  def test_pass(self):
    self.create_file('a/python/pass.py', contents=dedent("""
                       class UpperCase(object):
                         pass
                     """))
    target = self.make_target('a/python:pass', PythonLibrary, sources=['pass.py'])
    self.assertEqual(0, self.execute_task(target_roots=[target]))

  def test_failure(self):
    self.create_file('a/python/fail.py', contents=dedent("""
                        class lower_case(object):
                          pass
                       """))
    target = self.make_target('a/python:fail', PythonLibrary, sources=['fail.py'])
    with self.assertRaises(TaskError) as task_error:
      self.execute_task(target_roots=[target])
    self.assertIn('1 Python Style issues found', str(task_error.exception))

  def test_suppressed_file_passes(self):
    self.create_file('a/python/fail.py', contents=dedent("""
                        class lower_case(object):
                          pass
                       """))
    suppression_file = self.create_file('suppress.txt', contents=dedent("""
    a/python/fail\.py::variable-names"""))
    target = self.make_target('a/python:fail', PythonLibrary, sources=['fail.py'])
    self.set_options(suppress=suppression_file)
    self.assertEqual(0, self.execute_task(target_roots=[target]))

  def test_failure_fail_false(self):
    self.create_file('a/python/fail.py', contents=dedent("""
                        class lower_case(object):
                          pass
                     """))
    target = self.make_target('a/python:fail', PythonLibrary, sources=['fail.py'])
    self.set_options(fail=False)
    self.assertEqual(1, self.execute_task(target_roots=[target]))

  def test_syntax_error(self):
    self.create_file('a/python/error.py', contents=dedent("""
                         invalid python
                       """))
    target = self.make_target('a/python:error', PythonLibrary, sources=['error.py'])
    self.set_options(fail=False)
    self.assertEqual(1, self.execute_task(target_roots=[target]))

  def test_lint_for_py3_only_disabled(self):
    self.create_file('a/python/fail.py', contents=dedent("""
                         x=2+3
                         print(x+7)
                       """))
    target = self.make_target('a/python:fail', PythonLibrary, sources=['fail.py'],
      compatibility=['>=3.6'])
    self.set_options(fail=False)
    self.set_options(enable_py3_lint=False)
    self.assertEqual(0, self.execute_task(target_roots=[target]))

  def test_lint_for_py3_only_enabled(self):
    self.create_file('a/python/fail.py', contents=dedent("""
                         x=2+3
                         print(x+7)
                       """))
    target = self.make_target('a/python:fail', PythonLibrary, sources=['fail.py'],
      compatibility=['>=3.6'])
    self.set_options(enable_py3_lint=True)
    with self.assertRaises(TaskError) as task_error:
      self.execute_task(target_roots=[target])
    self.assertIn('3 Python Style issues found', str(task_error.exception))

  def test_lint_runs_for_py2_and_py3(self):
    self.create_file('a/python/fail_py2.py', contents=dedent("""
                         x=2+3
                         print x+7
                       """))
    target_py2 = self.make_target('a/python:fail2', PythonLibrary, sources=['fail_py2.py'],
      compatibility=['>=2.7,<3'])
    self.create_file('a/python/fail_py3.py', contents=dedent("""
                         x=2+3
                         print(x+7)
                       """))
    target_py3 = self.make_target('a/python:fail3', PythonLibrary, sources=['fail_py3.py'],
      compatibility=['>=3.6'])
    self.set_options(enable_py3_lint=True)
    with self.assertRaises(TaskError) as task_error:
      self.execute_task(target_roots=[target_py2, target_py3])
    self.assertIn('7 Python Style issues found', str(task_error.exception))

  def test_lint_runs_for_py2_and_skips_py3(self):
    self.create_file('a/python/fail_py2.py', contents=dedent("""
                         x=2+3
                         print x+7
                       """))
    target_py2 = self.make_target('a/python:fail2', PythonLibrary, sources=['fail_py2.py'],
      compatibility=['>=2.7,<3'])
    self.create_file('a/python/fail_py3.py', contents=dedent("""
                         x=2+3
                         print(x+7)
                       """))
    target_py3 = self.make_target('a/python:fail3', PythonLibrary, sources=['fail_py3.py'],
      compatibility=['>=3.6'])
    self.set_options(enable_py3_lint=False)
    with self.assertRaises(TaskError) as task_error:
      self.execute_task(target_roots=[target_py2, target_py3])
    self.assertIn('4 Python Style issues found', str(task_error.exception))
