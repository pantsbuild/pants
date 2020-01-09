# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.subsystems.zinc import Zinc
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.jvm_compile.jvm_compile import JvmCompile
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import BaseZincCompile
from pants.backend.jvm.tasks.nailgun_task import NailgunTaskBase
from pants.base.build_environment import get_buildroot
from pants.testutil.jvm.nailgun_task_test_base import NailgunTaskTestBase
from pants.testutil.subsystem.util import init_subsystems


class DummyJvmCompile(JvmCompile):
  compiler_name='dummy'

  def select(self, *args):
    return True

  def do_compile(self, invalidation_check, compile_contexts, classpath_product):
    """This mocks out do_compile by adding"""
    for vt in invalidation_check.invalid_vts:
      #classpath_product.add_for_target(vt.target, [])
      target = vt.target

      classpath_product.add_for_target(
        target,
        [(conf, os.path.join(self.get_options().pants_workdir, 'fake/classpath/for/target/z.jar')) for conf in self._confs],
      )


class JvmCompileTest(NailgunTaskTestBase):
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
    resulting_classpath = task.create_classpath_product()
    self.assertEqual([('default', pre_init_runtime_entry), ('default', compile_entry)],
      resulting_classpath.get_for_target(target))

  def test_modulized_targets_not_compiled_for_export_classpath(self):
    init_subsystems([JvmPlatform])
    targets = self.make_linear_graph(['a', 'b', 'c', 'd', 'e'], target_type=JavaLibrary)
    context = self.context(target_roots=[targets['a'], targets['c']], options={'jvm-platform': {'compiler': 'dummy'}})
    context.products.get_data('compile_classpath', ClasspathProducts.init_func(self.pants_workdir))
    # This should cause the jvm compile execution to exclude target roots and their
    # dependess from the set of relevant targets.
    context.products.require_data("export_dep_as_jar_classpath")
    self.execute(context)
    export_classpath = context.products.get_data('export_dep_as_jar_classpath')
    # assert none of the modulized targets have classpaths.
    self.assertFalse(export_classpath.get_for_target(targets['a']) + export_classpath.get_for_target(targets['b']) + export_classpath.get_for_target(targets['c']))
    self.assertTrue(export_classpath.get_for_target(targets['d']))
    self.assertTrue(export_classpath.get_for_target(targets['e']))

  def test_modulized_targets_are_compiled_when_runtime_classpath_is_requested(self):
    init_subsystems([JvmPlatform])
    targets = self.make_linear_graph(['a', 'b', 'c', 'd', 'e'], target_type=JavaLibrary)
    context = self.context(target_roots=[targets['a'], targets['c']], options={'jvm-platform': {'compiler': 'dummy'}})
    context.products.get_data('compile_classpath', ClasspathProducts.init_func(self.pants_workdir))
    # This should cause the jvm compile execution to exclude target roots and their
    # dependess from the set of relevant targets.
    context.products.require_data("export_dep_as_jar_classpath")
    context.products.require_data("runtime_classpath")
    self.execute(context)
    runtime_classpath = context.products.get_data('runtime_classpath')
    export_classpath = context.products.get_data('export_dep_as_jar_classpath')
    self.assertEqual(runtime_classpath, export_classpath)
    # assert all of the modulized targets have classpaths.
    self.assertTrue(export_classpath.get_for_target(targets['a']))
    self.assertTrue(export_classpath.get_for_target(targets['b']))
    self.assertTrue(export_classpath.get_for_target(targets['c']))


class BaseZincCompileJDKTest(NailgunTaskTestBase):
  DEFAULT_CONF = 'default'
  old_cwd = os.getcwd()

  @classmethod
  def task_type(cls):
    return BaseZincCompile

  def setUp(self):
    os.chdir(get_buildroot())
    super().setUp()

  def tearDown(self):
    os.chdir(self.old_cwd)
    super().tearDown()

  def test_subprocess_compile_jdk_being_symlink(self):
    context = self.context(target_roots=[])
    zinc = Zinc.Factory.global_instance().create(
      context.products, NailgunTaskBase.ExecutionStrategy.subprocess
    )
    self.assertTrue(os.path.islink(zinc.dist.home))

  def test_hermetic_jdk_being_underlying_dist(self):
    context = self.context(target_roots=[])
    zinc = Zinc.Factory.global_instance().create(
      context.products, NailgunTaskBase.ExecutionStrategy.hermetic
    )
    self.assertFalse(
      os.path.islink(zinc.dist.home),
      f"Expected {zinc.dist.home} to not be a link, it was."
    )
