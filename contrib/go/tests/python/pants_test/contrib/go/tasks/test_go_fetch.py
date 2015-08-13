# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.source_root import SourceRoot
from pants.base.target import Target
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, touch
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary
from pants.contrib.go.tasks.go_fetch import GoFetch


class GoFetchTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return GoFetch

  def setUp(self):
    super(GoFetchTest, self).setUp()
    self.go_fetch = self.create_task(self.context())

  def test_download_zip(self):
    with temporary_dir() as dest:
      with temporary_dir() as src:
        touch(os.path.join(src, 'mydir', 'myfile.go'))
        zfile = shutil.make_archive(os.path.join(src, 'mydir'), 'zip',
                                    root_dir=src, base_dir='mydir')
        self.go_fetch._download_zip('file://' + zfile, dest)
        self.assertTrue(os.path.isfile(os.path.join(dest, 'myfile.go')))

        with self.assertRaises(TaskError):
          self.go_fetch._download_zip('file://' + zfile + 'notreal', dest)

  def test_get_remote_import_ids(self):
    self.create_file('github.com/u/a/a.go', contents="""
      package a

      import (
        "fmt"
        "math"
        "sync"

        "github.com/u/b"
        "github.com/u/c"
      )
    """)
    pkg_dir = os.path.join(self.build_root, 'github.com/u/a')
    remote_import_ids = self.go_fetch._get_remote_import_ids(pkg_dir)
    self.assertItemsEqual(remote_import_ids,
                          ['github.com/u/b', 'github.com/u/c'])

  def test_resolve_and_inject(self):
    SourceRoot.register(os.path.join(self.build_root, '3rdparty'), Target)
    r1 = self.make_target(spec='3rdparty/github.com/u/r1', target_type=Target)
    self.add_to_build_file('3rdparty/github.com/u/r2',
                           'target(name="{}")'.format('r2'))
    r2 = self.go_fetch._resolve_and_inject(r1, 'github.com/u/r2')
    self.assertEqual(r2.name, 'r2')
    self.assertItemsEqual(r1.dependencies, [r2])

  def test_resolve_and_inject_failure(self):
    SourceRoot.register(os.path.join(self.build_root, '3rdparty'), Target)
    r1 = self.make_target(spec='3rdparty/github.com/u/r1', target_type=Target)
    with self.assertRaises(self.go_fetch.UndeclaredRemoteLibError) as cm:
      self.go_fetch._resolve_and_inject(r1, 'github.com/u/r2')
    self.assertEqual(cm.exception.spec_path, '3rdparty/github.com/u/r2')
