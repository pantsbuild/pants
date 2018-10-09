# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str
from textwrap import dedent

from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.exceptions import TaskError
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase

from pants.contrib.python.checks.tasks.checkstyle.checker import PythonCheckStyleTask
from pants.contrib.python.checks.tasks.checkstyle.variable_names_subsystem import \
  VariableNamesSubsystem


class PythonCheckStyleTaskTest(PythonTaskTestBase):
  @classmethod
  def task_type(cls):
    return PythonCheckStyleTask

  def setUp(self):
    super(PythonCheckStyleTaskTest, self).setUp()
    PythonCheckStyleTask.clear_plugins()
    PythonCheckStyleTask.register_plugin('variable-names', VariableNamesSubsystem)

  def tearDown(self):
    super(PythonCheckStyleTaskTest, self).tearDown()
    PythonCheckStyleTask.clear_plugins()

  def test_no_sources(self):
    task = self.create_task(self.context())
    self.assertEqual(None, task.execute())

  def test_pass(self):
    self.create_file('a/python/pass.py', contents=dedent("""
                       class UpperCase:
                         pass
                     """))
    target = self.make_target('a/python:pass', PythonLibrary, sources=['pass.py'])
    context = self.context(target_roots=[target])
    task = self.create_task(context)
    self.assertEqual(0, task.execute())

  def test_failure(self):
    self.create_file('a/python/fail.py', contents=dedent("""
                        class lower_case:
                          pass
                       """))
    target = self.make_target('a/python:fail', PythonLibrary, sources=['fail.py'])
    context = self.context(target_roots=[target])
    task = self.create_task(context)
    with self.assertRaises(TaskError) as task_error:
      task.execute()
    self.assertIn('1 Python Style issues found', str(task_error.exception))

  def test_suppressed_file_passes(self):
    self.create_file('a/python/fail.py', contents=dedent("""
                        class lower_case:
                          pass
                       """))
    suppression_file = self.create_file('suppress.txt', contents=dedent("""
    a/python/fail\.py::variable-names"""))
    target = self.make_target('a/python:fail', PythonLibrary, sources=['fail.py'])
    self.set_options(suppress=suppression_file)
    context = self.context(target_roots=[target], )
    task = self.create_task(context)
    self.assertEqual(0, task.execute())

  def test_failure_fail_false(self):
    self.create_file('a/python/fail.py', contents=dedent("""
                        class lower_case:
                          pass
                     """))
    target = self.make_target('a/python:fail', PythonLibrary, sources=['fail.py'])
    self.set_options(fail=False)
    context = self.context(target_roots=[target])
    task = self.create_task(context)
    self.assertEqual(1, task.execute())

  def test_syntax_error(self):
    self.create_file('a/python/error.py', contents=dedent("""
                         invalid python
                       """))
    target = self.make_target('a/python:error', PythonLibrary, sources=['error.py'])
    self.set_options(fail=False)
    context = self.context(target_roots=[target])
    task = self.create_task(context)

    self.assertEqual(1, task.execute())

  def test_failure_print_nit(self):
    self.create_file('a/python/fail.py', contents=dedent("""
                        class lower_case:
                          pass
                       """))
    target = self.make_target('a/python:fail', PythonLibrary, sources=['fail.py'])
    context = self.context(target_roots=[target])
    task = self.create_task(context)

    nits = list(task.get_nits('a/python/fail.py'))

    self.assertEqual(1, len(nits))
    self.assertEqual(
      """T000:ERROR   a/python/fail.py:002 Classes must be UpperCamelCased\n"""
      """     |class lower_case:""",
      str(nits[0]))

  def test_syntax_error_nit(self):
    self.create_file('a/python/error.py', contents=dedent("""
                         invalid python
                       """))
    target = self.make_target('a/python:error', PythonLibrary, sources=['error.py'])
    self.set_options(fail=False)
    context = self.context(target_roots=[target])
    task = self.create_task(context)

    nits = list(task.get_nits('a/python/error.py'))

    self.assertEqual(1, len(nits))
    self.assertEqual("""E901:ERROR   a/python/error.py:002 SyntaxError: invalid syntax\n"""
                     """     |\n"""
                     """     |invalid python\n"""
                     """     |""",
                     str(nits[0]))

  def test_context_has_python_3_compatible_targets_helper(self):
    """
    Test the helper method for detecting whether a target set contains python 3 targets.
    TODO(clivingston): delete this when the following ticket is resolved:
    https://github.com/pantsbuild/pants/issues/5764
    """
    func = PythonCheckStyleTask._context_has_python_3_compatible_targets
    case_1 = {
      ('CPython>3',): [None],
      ('CPython<3',): [None]
    }
    case_2 = {
      ('CPython>3.3.5',): [None],
      ('CPython>=2.7,<3',): [None]
    }
    case_3 = {
      ('CPython>3,<4',): [None],
      ('CPython>=2.7,<3',): [None]
    }
    case_4 = {
      ('CPython>2.7.10',): [None],
      ('CPython>=2.7,<3',): [None]
    }
    case_5 = {
      ('CPython<3',): [None],
      ('CPython>=2.7.10,<3',): [None]
    }

    constraint_cases_with_py3 = [case_1, case_2, case_3]
    for case in constraint_cases_with_py3:
      self.assertEqual(func(case), True)
      self.assertEqual(len(case), 1)

    # Test contexts with constraints for Py2-only.
    self.assertEqual(func(case_4), True)
    self.assertEqual(len(case_4), 1)

    self.assertEqual(func(case_5), False)
    self.assertEqual(len(case_5), 2)
