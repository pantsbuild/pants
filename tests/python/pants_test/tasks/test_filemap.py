# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from textwrap import dedent

from pants.tasks.filemap import Filemap
from pants_test.tasks.test_base import ConsoleTaskTest


class FilemapTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return Filemap

  @classmethod
  def setUpClass(cls):
    super(FilemapTest, cls).setUpClass()

    def create_target(path, name, *files):
      for f in files:
        cls.create_file(os.path.join(path, f), '')

      cls.create_target(path, dedent('''
          python_library(name='%s',
            sources=[%s]
          )
          ''' % (name, ','.join(repr(f) for f in files))))

    cls.create_target('common', 'source_root.here(python_library)')
    create_target('common/a', 'a', 'one.py')
    create_target('common/b', 'b', 'two.py', 'three.py')
    create_target('common/c', 'c', 'four.py')

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
