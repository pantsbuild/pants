# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants_test.jvm.jvm_task_test_mixin import JvmTaskTestMixin
from pants_test.tasks.task_test_base import TaskTestBase


class DummyJvmTask(JvmTask):
  def execute(self):
    pass


class JvmTaskTest(JvmTaskTestMixin, TaskTestBase):
  """Test some base functionality in JvmTask."""

  @classmethod
  def task_type(cls):
    return DummyJvmTask

  def setUp(self):
    super(JvmTaskTest, self).setUp()

    self.t1 = self.make_target('t1')
    self.t2 = self.make_target('t2')
    self.t3 = self.make_target('t3')

    context = self.context(target_roots=[self.t1, self.t2, self.t3])

    self.classpath = [os.path.join(self.build_root, entry) for entry in 'a', 'b']
    self.populate_runtime_classpath(context, self.classpath)

    self.task = self.create_task(context)

  def test_classpath(self):
    self.assertEqual(self.classpath, self.task.classpath([self.t1]))
    self.assertEqual(self.classpath, self.task.classpath([self.t2]))
    self.assertEqual(self.classpath, self.task.classpath([self.t3]))
    self.assertEqual(self.classpath, self.task.classpath([self.t1, self.t2, self.t3]))
