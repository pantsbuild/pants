# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.build_graph.target import Target
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import touch
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.tasks.go_binary_create import GoBinaryCreate


class GoBinaryCreateTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return GoBinaryCreate

  def test_noop_empty(self):
    task = self.create_task(self.context())
    task.execute()
    self.assertFalse(os.path.exists(task.dist_root))

  def test_noop_na(self):
    task = self.create_task(self.context(target_roots=[self.make_target(':a', Target)]))
    task.execute()
    self.assertFalse(os.path.exists(task.dist_root))

  def test_execute(self):
    with temporary_dir() as bin_source_dir:
      def create_binary(name):
        target = self.make_target(name, GoBinary)
        executable = os.path.join(bin_source_dir, '{}.exe'.format(name))
        touch(executable)
        return target, executable

      a, a_exe = create_binary('thing/a')
      b, b_exe = create_binary('thing/b')

      context = self.context(target_roots=[a, b])
      context.products.safe_create_data('exec_binary', init_func=lambda: {a: a_exe, b: b_exe})

      task = self.create_task(context)
      task.execute()

      binaries = self.buildroot_files(task.dist_root)
      rel_dist_root = os.path.relpath(task.dist_root, self.build_root)
      self.assertEqual({os.path.join(rel_dist_root, os.path.basename(a_exe)),
                        os.path.join(rel_dist_root, os.path.basename(b_exe))},
                       binaries)
