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


class GoWorkspaceTaskTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return GoWorkspaceTask

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
      spec = 'foo/bar/mylib'
      sources = ['x.go', 'y.go', 'z.go']
      for src in sources:
        self.create_file(os.path.join(spec, src))

      go_lib = self.make_target(spec=spec, target_type=GoLibrary)
      ws_task = self.create_task(self.context())
      gopath = ws_task.get_gopath(go_lib)

      def islinked(src):
        link = os.path.join(gopath, 'src', spec, src)
        return (os.path.islink(link) and
                (os.readlink(link) == os.path.join(self.build_root, spec, src)))

      ws_task._symlink_local_src(gopath, go_lib, set())
      for src in sources:
        self.assertTrue(islinked(src))

      # Sleep so that first round of linking has 1 second earlier mtime than future links.
      time.sleep(1)

      # Add source file and re-make library.
      self.create_file(os.path.join(spec, 'w.go'))
      self.reset_build_graph()
      go_lib = self.make_target(spec=spec, target_type=GoLibrary)

      ws_task._symlink_local_src(gopath, go_lib, set())
      for src in chain(sources, ['w.go']):
        self.assertTrue(islinked(src))

      mtime = lambda src: os.lstat(os.path.join(gopath, 'src', spec, src)).st_mtime
      for src in sources:
        # Ensure none of the old links were overwritten.
        self.assertTrue(mtime(src) <= mtime('w.go') - 1)

  def test_symlink_remote_lib(self):
    with pushd(self.build_root):
      with temporary_dir() as d:
        spec = 'github.com/user/lib'
        src_dir = os.path.join(d, spec)
        go_remote_lib = self.make_target(spec=spec, target_type=GoRemoteLibrary,
                                         rev='', zip_url='')
        context = self.context()
        context.products.get_data('go_remote_lib_src',
                                  init_func=lambda: defaultdict(str))[go_remote_lib] = src_dir
        ws_task = self.create_task(context)

        # Monkey patch global_import_id to not use source roots when resolving import id.
        ws_task.global_import_id = lambda target: target.address.spec_path

        gopath = ws_task.get_gopath(go_remote_lib)
        ws_task._symlink_remote_lib(gopath, go_remote_lib, set())
        link = os.path.join(gopath, 'src', spec)
        self.assertTrue(os.path.islink(link) and
                        os.readlink(link) == os.path.join(d, spec))
