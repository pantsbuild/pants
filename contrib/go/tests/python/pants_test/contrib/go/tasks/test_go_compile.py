# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import time

from pants.util.dirutil import touch
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.go.targets.go_library import GoLibrary
from pants.contrib.go.tasks.go_compile import GoCompile


class GoCompileTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return GoCompile

  def setUp(self):
    super(GoCompileTest, self).setUp()
    self.go_compile = self.create_task(self.context())

  def _create_binary(self, target):
    p = os.path.join(self.go_compile.get_gopath(target), 'pkg', target.address.spec)
    touch(p)
    return p

  def _create_lib_binary_map(self, *args):
    m = {}
    for target in args:
      m[target] = self._create_binary(target)
    return m

  def test_sync_binary_dep_links_basic(self):
    b = self.make_target(spec='libB', target_type=GoLibrary)
    a = self.make_target(spec='libA', target_type=GoLibrary, dependencies=[b])
    lib_binary_map = self._create_lib_binary_map(a, b)

    a_gopath = self.go_compile.get_gopath(a)
    self.go_compile._sync_binary_dep_links(a, a_gopath, lib_binary_map)

    b_link = os.path.join(a_gopath, 'pkg', b.address.spec)
    self.assertTrue(os.path.islink(b_link))
    self.assertEqual(os.readlink(b_link), lib_binary_map[b])

  def test_sync_binary_dep_links_removes_unused_links(self):
    b = self.make_target(spec='libB', target_type=GoLibrary)
    a = self.make_target(spec='libA', target_type=GoLibrary, dependencies=[b])
    lib_binary_map = self._create_lib_binary_map(a, b)

    a_gopath = self.go_compile.get_gopath(a)
    self.go_compile._sync_binary_dep_links(a, a_gopath, lib_binary_map)

    b_link = os.path.join(a_gopath, 'pkg', b.address.spec)

    # Remove b as dependency of a and assert a's pkg/ dir no longer contains link to b.
    self.reset_build_graph()
    b = self.make_target(spec='libB', target_type=GoLibrary)
    a = self.make_target(spec='libA', target_type=GoLibrary)
    self.go_compile._sync_binary_dep_links(a, a_gopath, lib_binary_map)
    self.assertFalse(os.path.islink(b_link))

  def test_sync_binary_dep_links_refreshes_links(self):
    c = self.make_target(spec='libC', target_type=GoLibrary)
    b = self.make_target(spec='libB', target_type=GoLibrary)
    a = self.make_target(spec='libA', target_type=GoLibrary, dependencies=[b, c])
    lib_binary_map = self._create_lib_binary_map(a, b, c)

    a_gopath = self.go_compile.get_gopath(a)
    self.go_compile._sync_binary_dep_links(a, a_gopath, lib_binary_map)

    # Ensure future links are older than original links by at least 1.5 seconds.
    time.sleep(1.5)

    # "Modify" b's binary.
    touch(lib_binary_map[b])

    self.go_compile._sync_binary_dep_links(a, a_gopath, lib_binary_map)

    mtime = lambda t: os.lstat(os.path.join(os.path.join(a_gopath, 'pkg', t.address.spec))).st_mtime
    # Make sure c's link was untouched, while b's link was refreshed.
    self.assertLessEqual(mtime(c), mtime(b) - 1)
