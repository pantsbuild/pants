# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from textwrap import dedent

from pants.backend.core.tasks.filemap import Filemap
from pants.base.source_root import SourceRoot
from pants.backend.python.targets.python_library import PythonLibrary
from pants_test.tasks.test_base import ConsoleTaskTest


class FilemapTest(ConsoleTaskTest):
  @property
  def alias_groups(self):
    return {
      'target_aliases': {
        'python_library': PythonLibrary,
      },
      'applicative_path_relative_utils': {
        'source_root': SourceRoot,
      },
    }

  @classmethod
  def task_type(cls):
    return Filemap

  def setUp(self):
    super(FilemapTest, self).setUp()

    def add_to_build_file(path, name, *files):
      for f in files:
        self.create_file(os.path.join(path, f), '')

      self.add_to_build_file(path, dedent('''
          python_library(name='%s',
            sources=[%s]
          )
          ''' % (name, ','.join(repr(f) for f in files))))

    self.add_to_build_file('common', 'source_root.here(python_library)')
    add_to_build_file('common/a', 'a', 'one.py')
    add_to_build_file('common/b', 'b', 'two.py', 'three.py')
    add_to_build_file('common/c', 'c', 'four.py')
    add_to_build_file('common', 'dummy')
    self.target('common/b')

  def test_all(self):
    self.assert_console_output(
      'common/a/one.py common/a/BUILD:a',
      'common/b/two.py common/b/BUILD:b',
      'common/b/three.py common/b/BUILD:b',
      'common/c/four.py common/c/BUILD:c',
    )

  def test_one(self):
    self.assert_console_output(
      'common/b/two.py common/b/BUILD:b',
      'common/b/three.py common/b/BUILD:b',
      targets=[self.target('common/b')]
    )

  def test_dup(self):
    self.assert_console_output(
      'common/a/one.py common/a/BUILD:a',
      'common/c/four.py common/c/BUILD:c',
      targets=[self.target('common/a'), self.target('common/c'), self.target('common/a')]
    )
