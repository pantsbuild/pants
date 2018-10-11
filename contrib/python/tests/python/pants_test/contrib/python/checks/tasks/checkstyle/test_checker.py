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
from pants.backend.python.tasks.select_interpreter import SelectInterpreter
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
                           '--run=bdist_wheel',
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
      si_task_type = self.synthesize_task_subtype(SelectInterpreter, 'si_scope')
      context = self.context(for_task_types=[si_task_type], target_roots=target_roots)
      si_task_type(context, os.path.join(self.pants_workdir, 'si')).execute()
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
