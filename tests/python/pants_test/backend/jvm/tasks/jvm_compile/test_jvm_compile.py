# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.backend.jvm.subsystems.zinc import Zinc
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.jvm_compile.jvm_compile import JvmCompile
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import BaseZincCompile
from pants.backend.jvm.tasks.nailgun_task import NailgunTaskBase
from pants_test.task_test_base import TaskTestBase


class DummyJvmCompile(JvmCompile):
  pass


class JvmCompileTest(TaskTestBase):
  DEFAULT_CONF = 'default'

  @classmethod
  def task_type(cls):
    return DummyJvmCompile

  def test_if_runtime_classpath_exists(self):
    target = self.make_target(
      'java/classpath:java_lib',
      target_type=JavaLibrary,
      sources=['com/foo/Bar.java'],
    )

    context = self.context(target_roots=[target])
    compile_classpath = context.products.get_data('compile_classpath', ClasspathProducts.init_func(self.pants_workdir))

    compile_entry = os.path.join(self.pants_workdir, 'compile-entry')
    pre_init_runtime_entry = os.path.join(self.pants_workdir, 'pre-inited-runtime-entry')
    compile_classpath.add_for_targets([target], [('default', compile_entry)])
    runtime_classpath = context.products.get_data('runtime_classpath', ClasspathProducts.init_func(self.pants_workdir))

    runtime_classpath.add_for_targets([target], [('default', pre_init_runtime_entry)])

    task = self.create_task(context)
    resulting_classpath = task.create_runtime_classpath()
    self.assertEqual([('default', pre_init_runtime_entry), ('default', compile_entry)],
      resulting_classpath.get_for_target(target))


class BaseZincCompileJDKTest(TaskTestBase):
  DEFAULT_CONF = 'default'

  @classmethod
  def task_type(cls):
    return BaseZincCompile

  def test_subprocess_compile_jdk_being_symlink(self):
    dummy_target = self.make_target(
      'java/classpath:java_lib',
      target_type=JavaLibrary,
      sources=['com/foo/Bar.java'],
    )

    context = self.context(target_roots=[dummy_target])
    zinc = Zinc.Factory.global_instance().create(context.products, NailgunTaskBase.SUBPROCESS)
    self.assertTrue(os.path.islink(zinc.dist.home))

  def test_hermetic_jdk_being_underlying_dist(self):
    dummy_target = self.make_target(
      'java/classpath:java_lib',
      target_type=JavaLibrary,
      sources=['com/foo/Bar.java'],
    )

    context = self.context(target_roots=[dummy_target])
    zinc = Zinc.Factory.global_instance().create(context.products, NailgunTaskBase.HERMETIC)
    self.assertFalse(os.path.islink(zinc.dist.home))
