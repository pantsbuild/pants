# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.backend.core.tasks.filemap import Filemap
from pants.backend.python.targets.python_library import PythonLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class FilemapTest(ConsoleTaskTestBase):
  @property
  def alias_groups(self):
    return BuildFileAliases(
      targets={
        'python_library': PythonLibrary,
      },
    )

  @classmethod
  def task_type(cls):
    return Filemap

  def setUp(self):
    super(FilemapTest, self).setUp()

    def add_to_build_file(path, name, *files):
      for f in files:
        self.create_file(os.path.join(path, f), '')

      self.add_to_build_file(path, dedent("""
          python_library(name='{name}',
            sources=[{sources}]
          )
          """.format(name=name, sources=','.join(repr(f) for f in files))))

    add_to_build_file('common/src/py/a', 'a', 'one.py')
    add_to_build_file('common/src/py/b', 'b', 'two.py', 'three.py')
    add_to_build_file('common/src/py/c', 'c', 'four.py')
    add_to_build_file('common', 'dummy')
    self.target('common/src/py/b')

  def test_all(self):
    self.assert_console_output(
      'common/src/py/a/one.py common/src/py/a:a',
      'common/src/py/b/two.py common/src/py/b:b',
      'common/src/py/b/three.py common/src/py/b:b',
      'common/src/py/c/four.py common/src/py/c:c',
    )

  def test_one(self):
    self.assert_console_output(
      'common/src/py/b/two.py common/src/py/b:b',
      'common/src/py/b/three.py common/src/py/b:b',
      targets=[self.target('common/src/py/b')]
    )

  def test_dup(self):
    self.assert_console_output(
      'common/src/py/a/one.py common/src/py/a:a',
      'common/src/py/c/four.py common/src/py/c:c',
      targets=[self.target('common/src/py/a'),
               self.target('common/src/py/c'),
               self.target('common/src/py/a')]
    )
