# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
import sys
from textwrap import dedent

from pytest import fail

from pants.backend.python.tasks.python_isort import IsortPythonTask
from pants.base.exceptions import TaskError
from pants.util.contextutil import temporary_file
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase


class PythonIsortIntegrationTest(PythonTaskTestBase):

  BAD_IMPORT_ORDER = dedent("""
  from __future__ import (with_statement, division, absolute_import, generators, nested_scopes, print_function,
                          unicode_literals)

  """)

  CONFIG_A = dedent("""
    [settings]
    line_length=100
    known_future_library=future,pies
    multi_line_output=0
  """)

  RESULT_A = dedent("""
    from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                            unicode_literals, with_statement)
  """)

  CONFIG_B = dedent("""
    [settings]
    line_length=100
    known_future_library=future,pies
    multi_line_output=1
  """)

  RESULT_B = dedent("""
    from __future__ import (absolute_import,
                            division,
                            generators,
                            nested_scopes,
                            print_function,
                            unicode_literals,
                            with_statement)
  """)

  @classmethod
  def task_type(cls):
    return IsortPythonTask

  def setUp(self):
    super(PythonIsortIntegrationTest, self).setUp()
    self._create_graph()

  def _create_graph(self):
    self.reset_build_graph()
    # super(AbcTest, self).context()
    self.a_library = self.create_python_library('src/python/a', 'a',
                                                {'a_1.py': self.BAD_IMPORT_ORDER,
                                                 'a_2.py': self.BAD_IMPORT_ORDER})
    self._write_to_file(os.path.join(self.build_root, 'src/python/a/not_in_a_target.py'), self.BAD_IMPORT_ORDER)
    self._write_to_file(os.path.join(self.build_root, 'src/python/a/.isort.cfg'), self.CONFIG_A)

    self.b_library = self.create_python_library('src/python/a/b', 'b', {'b.py': self.BAD_IMPORT_ORDER})

    self.c_library = self.create_python_library('src/python/c', 'c', {'c.py': self.BAD_IMPORT_ORDER})

    self._write_to_file(os.path.join(self.build_root, 'src/.isort.cfg'), self.CONFIG_B)

    self.d_resources = self.create_resources('src/python/r', 'r', 'r.py')
    self._write_to_file(os.path.join(self.build_root, 'src/python/r/r.py'), self.BAD_IMPORT_ORDER)

  def _create_task(self, target_roots, options=None, passthru_args=None):
    if options:
      self.set_options(**options)
    return self.create_task(self.context(target_roots=target_roots, passthru_args=passthru_args))

  def test_isort_single_target(self):
    isort_task = self._create_task(target_roots=[self.a_library])
    isort_task.execute()
    self._assertFileContent(os.path.join(self.build_root, 'src/python/a/a_1.py'), self.RESULT_A)
    self._assertFileContent(os.path.join(self.build_root, 'src/python/a/a_2.py'), self.RESULT_A)
    self._assertFileContent(os.path.join(self.build_root, 'src/python/a/b/b.py'), self.BAD_IMPORT_ORDER)
    self._assertFileContent(os.path.join(self.build_root, 'src/python/a/not_in_a_target.py'), self.BAD_IMPORT_ORDER)

  # No target or passthru specified, should behave as ./pants fmt.isort ::,
  # so every py file in a python target should be sorted.
  def test_isort_no_target_no_passthru(self):
    isort_task = self._create_task(target_roots=[])
    isort_task.execute()
    self._assertFileContent(os.path.join(self.build_root, 'src/python/a/a_1.py'), self.RESULT_A)
    self._assertFileContent(os.path.join(self.build_root, 'src/python/a/a_2.py'), self.RESULT_A)
    self._assertFileContent(os.path.join(self.build_root, 'src/python/a/b/b.py'), self.RESULT_A)
    self._assertFileContent(os.path.join(self.build_root, 'src/python/a/not_in_a_target.py'), self.BAD_IMPORT_ORDER)
    self._assertFileContent(os.path.join(self.build_root, 'src/python/c/c.py'), self.RESULT_B)
    self._assertFileContent(os.path.join(self.build_root, 'src/python/r/r.py'), self.BAD_IMPORT_ORDER)

  def test_isort_passthru_no_target(self):
    isort_task = self._create_task(target_roots=[], passthru_args=['--recursive', '.'])
    isort_task.execute()
    self._assertFileContent(os.path.join(self.build_root, 'src/python/a/a_1.py'), self.RESULT_A)
    self._assertFileContent(os.path.join(self.build_root, 'src/python/a/a_2.py'), self.RESULT_A)
    self._assertFileContent(os.path.join(self.build_root, 'src/python/a/b/b.py'), self.RESULT_A)
    self._assertFileContent(os.path.join(self.build_root, 'src/python/a/not_in_a_target.py'), self.RESULT_A)
    self._assertFileContent(os.path.join(self.build_root, 'src/python/c/c.py'), self.RESULT_B)
    self._assertFileContent(os.path.join(self.build_root, 'src/python/r/r.py'), self.RESULT_B)

  # Resources should not be touched. Hence noop isort.
  def test_isort_isortable_target(self):
    isort_task = self._create_task(target_roots=[self.d_resources])
    isort_task.execute()
    self._assertFileContent(os.path.join(self.build_root, 'src/python/r/r.py'), self.BAD_IMPORT_ORDER)

  def test_isort_check_only(self):
    isort_task = self._create_task(target_roots=[self.a_library], passthru_args=['--check-only'])
    with temporary_file() as f:
      try:
        isort_task.execute(test_output_file=f)
        pass
      except TaskError:
        with open(f.name) as x:
          output = x.read()
          self.assertIn("a_1.py Imports are incorrectly sorted.", output)
          self.assertIn("a_2.py Imports are incorrectly sorted.", output)
      else:
        fail("--check-only test for {} is supposed to fail, but passed.".format(self.a_library))

  @staticmethod
  def _write_to_file(path, content):
    with open(path, 'w') as f:
      f.write(content)

  def _assertFileContent(self, path, content):
    with open(path) as f:
      self.assertEqual(content, f.read())
