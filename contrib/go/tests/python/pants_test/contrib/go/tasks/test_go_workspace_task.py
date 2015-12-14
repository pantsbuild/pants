# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import time
from collections import defaultdict
from itertools import chain

from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import safe_mkdir, touch
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.go.targets.go_library import GoLibrary
from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary
from pants.contrib.go.tasks.go_workspace_task import GoWorkspaceTask


class MockGoWorkspaceTask(GoWorkspaceTask):
  """Used to test instance methods of abstract class GoWorkspaceTask."""

  def execute(self):
    pass


class GoWorkspaceTaskTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return MockGoWorkspaceTask

  def test_remove_unused_links(self):
    with temporary_dir() as d:
      dpath = lambda p: os.path.join(d, p)
      safe_mkdir(dpath('foo'))
      safe_mkdir(dpath('bar'))
      touch(dpath('f'))
      for l in ('l1', 'foo/l2', 'bar/l3'):
        # Create symlinks to directories.
        os.symlink('/', dpath(l))
      for l in ('l4', 'foo/l5', 'bar/l6'):
        # Create symlinks to files.
        os.symlink(dpath('f'), dpath(l))

      required_links = [dpath(l) for l in ('foo/l2', 'l4', 'bar/l6')]
      GoWorkspaceTask.remove_unused_links(d, required_links)

      for p in chain(required_links, ['f']):
        self.assertTrue(os.path.exists(dpath(p)))

      for l in ('l1', 'bar/l3', 'foo/l5'):
        self.assertFalse(os.path.exists(dpath(l)))

  def test_symlink_local_src(self):
    with pushd(self.build_root):
      spec = 'src/main/go/foo/bar/mylib'

      sources = ['x.go', 'y.go', 'z.go', 'z.c', 'z.h', 'w.png']
      for src in sources:
        self.create_file(os.path.join(spec, src))

      go_lib = self.make_target(spec=spec, target_type=GoLibrary)
      ws_task = self.create_task(self.context())
      gopath = ws_task.get_gopath(go_lib)

      def assert_is_linked(src):
        link = os.path.join(gopath, 'src/foo/bar/mylib', src)
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.readlink(link), os.path.join(self.build_root, spec, src))

      ws_task._symlink_local_src(gopath, go_lib, set())
      for src in sources:
        assert_is_linked(src)

      # Sleep so that first round of linking has 1.5 second earlier mtime than future links.
      time.sleep(1.5)

      # Add source file and re-make library.
      self.create_file(os.path.join(spec, 'w.go'))
      self.reset_build_graph()
      go_lib = self.make_target(spec=spec, target_type=GoLibrary)

      ws_task._symlink_local_src(gopath, go_lib, set())
      for src in chain(sources, ['w.go']):
        assert_is_linked(src)

      mtime = lambda src: os.lstat(os.path.join(gopath, 'src/foo/bar/mylib', src)).st_mtime
      for src in sources:
        # Ensure none of the old links were overwritten.
        self.assertLessEqual(mtime(src), mtime('w.go') - 1)

  def test_symlink_remote_lib(self):
    with pushd(self.build_root):
      with temporary_dir() as d:
        spec = '3rdparty/go/github.com/user/lib'

        remote_lib_src_dir = os.path.join(d, spec)
        remote_files = ['file.go', 'file.cc', 'file.hh']
        for remote_file in remote_files:
          self.create_file(os.path.join(remote_lib_src_dir, remote_file))

        go_remote_lib = self.make_target(spec=spec, target_type=GoRemoteLibrary)

        context = self.context()
        go_remote_lib_src = context.products.get_data('go_remote_lib_src',
                                                      init_func=lambda: defaultdict(str))
        go_remote_lib_src[go_remote_lib] = remote_lib_src_dir

        ws_task = self.create_task(context)

        gopath = ws_task.get_gopath(go_remote_lib)
        ws_task._symlink_remote_lib(gopath, go_remote_lib, set())
        workspace_dir = os.path.join(gopath, 'src/github.com/user/lib')
        self.assertTrue(os.path.isdir(workspace_dir))

        for remote_file in remote_files:
          link = os.path.join(workspace_dir, remote_file)
          self.assertEqual(os.readlink(link), os.path.join(remote_lib_src_dir, remote_file))
