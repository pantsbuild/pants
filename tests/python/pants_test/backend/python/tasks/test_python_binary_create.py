# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.python.tasks.python_binary_create import PythonBinaryCreate
#from pants.util.contextutil import temporary_file_path
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase


class PythonBinaryCreateTest(PythonTaskTestBase):
  @classmethod
  def task_type(cls):
    return PythonBinaryCreate

  def setUp(self):
    super(PythonBinaryCreateTest, self).setUp()

    self.library = self.create_python_library('src/python/lib', 'lib', {'lib.py': dedent("""
    import os


    def main():
      os.getcwd()
    """)})

    self.binary = self.create_python_binary('src/python/bin', 'bin', 'lib.lib:main',
                                            dependencies=['//src/python/lib'])

  def test_foo(self):
    self.assertTrue(True)
