# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.jvmdoc_gen import Jvmdoc, JvmdocGen
from pants.base.exceptions import TaskError
from pants_test.jvm.jvm_task_test_base import JvmTaskTestBase


dummydoc = Jvmdoc(tool_name='dummydoc', product_type='dummydoc')


class DummyJvmdocGen(JvmdocGen):
  @classmethod
  def jvmdoc(cls):
    return dummydoc

  def execute(self):
    self.generate_doc(lambda t: True, create_dummydoc_command)


def create_dummydoc_command(classpath, gendir, *targets):
  # here we need to test that we get the expected classpath
  pass


class JvmdocGenTest(JvmTaskTestBase):
  """Test some base functionality in JvmdocGen."""

  @classmethod
  def task_type(cls):
    return DummyJvmdocGen

  def setUp(self):
    super(JvmdocGenTest, self).setUp()

    self.t1 = self.make_target('t1')
    context = self.context(target_roots=[self.t1])

    self.targets = context.targets()

    self.populate_runtime_classpath(context)

    self.task = self.create_task(context)

  def test_classpath(self):
    self.task.execute()

  def test_generate(self):
    def create_jvmdoc_command_fail(classpath, gendir, *targets):
      return os.path.join(os.path.dirname(__file__), "false.py")
    def create_jvmdoc_command_succeed(classpath, gendir, *targets):
      return os.path.join(os.path.dirname(__file__), "true.py")

    for generate in [self.task._generate_individual,
                     self.task._generate_combined]:
      with self.assertRaises(TaskError):
        generate(self.targets, create_jvmdoc_command_fail)

      generate(self.targets, create_jvmdoc_command_succeed)
