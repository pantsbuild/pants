# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_mkdtemp, safe_rmtree
from pants_test.tasks.task_test_base import TaskTestBase


class DummyJvmTask(JvmTask):
  def execute(self):
    pass


class JvmTaskTest(TaskTestBase):
  """Test some base functionality in JvmTask."""

  @classmethod
  def task_type(cls):
    return DummyJvmTask

  def setUp(self):
    super(JvmTaskTest, self).setUp()
    self.workdir = safe_mkdtemp()

    self.t1 = self.make_target('t1')
    self.t2 = self.make_target('t2')
    self.t3 = self.make_target('t3')

    context = self.context(target_roots=[self.t1, self.t2, self.t3])

    self.populate_compile_classpath(context)

    self.task = self.create_task(context, self.workdir)

  def tearDown(self):
    super(JvmTaskTest, self).tearDown()
    safe_rmtree(self.workdir)
