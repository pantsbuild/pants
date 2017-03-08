# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
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

    self.t2 = self.make_target('t2')
    self.t1 = self.make_target('t1', dependencies=[self.t2])

    context = self.context(target_roots=[self.t1])
    self.context = context
    self.targets = context.targets()

    self.populate_runtime_classpath(context)

    self.task = self.create_task(context)

  def test_classpath(self):
    self.task.execute()

  def test_generate(self):
    def create_jvmdoc_command_fail(classpath, gendir, *targets):
      return ['python', os.path.join(os.path.dirname(__file__), "false.py")]
    def create_jvmdoc_command_succeed(classpath, gendir, *targets):
      return ['python', os.path.join(os.path.dirname(__file__), "true.py")]

    for generate in [self.task._generate_individual,
                     self.task._generate_combined]:
      with self.assertRaises(TaskError):
        generate(lambda t: True, self.targets, create_jvmdoc_command_fail)

      generate(lambda t: True, self.targets, create_jvmdoc_command_succeed)

  def test_classpath_filtered_by_lang_predicate(self):

    def expect_classpath_missing_filtered(classpath, gendir, *targets):
      self.assertEqual([], classpath)
      return ['python', os.path.join(os.path.dirname(__file__), "true.py")]
    classpath = self.context.products.get_data('runtime_classpath', ClasspathProducts.init_func(self.pants_workdir))
    classpath.add_for_targets([self.t2], [('default', os.path.join(self.pants_workdir, 't2-jar'))])

    for generate in [self.task._generate_individual,
      self.task._generate_combined]:
      generate(lambda t: t != self.t2, [self.t1], expect_classpath_missing_filtered)
