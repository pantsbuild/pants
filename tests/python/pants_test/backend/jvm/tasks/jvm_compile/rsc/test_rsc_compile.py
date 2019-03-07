# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from textwrap import dedent

from pants.backend.jvm.subsystems.junit import JUnit
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.jvm_compile.execution_graph import ExecutionGraph
from pants.backend.jvm.tasks.jvm_compile.rsc.rsc_compile import RscCompile, _create_desandboxify_fn
from pants.java.jar.jar_dependency import JarDependency
from pants.util.contextutil import temporary_dir
from pants_test.subsystem.subsystem_util import init_subsystem
from pants_test.task_test_base import TaskTestBase


class LightWeightVTS(object):
  # Simple test double that covers the properties referred to by the _compile_jobs method.

  def __init__(self, target):
    self.target = target

  def update(self):
    pass

  def force_invalidate(self):
    pass


class RscCompileTest(TaskTestBase):
  DEFAULT_CONF = 'default'

  @classmethod
  def task_type(cls):
    return RscCompile

  def test_no_dependencies_between_scala_and_java_targets(self):
    self.init_dependencies_for_scala_libraries()

    java_target = self.make_target(
      'java/classpath:java_lib',
      target_type=JavaLibrary,
      sources=['com/example/Foo.java'],
      dependencies=[]
    )
    scala_target = self.make_target(
      'scala/classpath:scala_lib',
      target_type=ScalaLibrary,
      sources=['com/example/Foo.scala'],
      dependencies=[]
    )

    with temporary_dir() as tmp_dir:
      invalid_targets = [java_target, scala_target]
      task = self.create_task_with_target_roots(
        target_roots=[java_target]
      )

      jobs = task._create_compile_jobs(
        compile_contexts=self.create_compile_contexts([java_target, scala_target], task, tmp_dir),
        invalid_targets=invalid_targets,
        invalid_vts=self.wrap_in_vts(invalid_targets),
        classpath_product=None)

      dependee_graph = self.construct_dependee_graph_str(jobs, task)
      print(dependee_graph)
      self.assertEqual(dedent("""
                     zinc(java/classpath:java_lib) -> {}
                     rsc(scala/classpath:scala_lib) -> {
                       zinc_against_rsc(scala/classpath:scala_lib)
                     }
                     zinc_against_rsc(scala/classpath:scala_lib) -> {}""").strip(),
        dependee_graph)

  def test_rsc_dep_for_scala_java_and_test_targets(self):
    self.init_dependencies_for_scala_libraries()

    scala_dep = self.make_target(
      'scala/classpath:scala_dep',
      target_type=ScalaLibrary,
      sources=['com/example/Bar.scala']
    )
    java_target = self.make_target(
      'java/classpath:java_lib',
      target_type=JavaLibrary,
      sources=['com/example/Foo.java'],
      dependencies=[scala_dep]
    )
    scala_target = self.make_target(
      'scala/classpath:scala_lib',
      target_type=ScalaLibrary,
      sources=['com/example/Foo.scala'],
      dependencies=[scala_dep]
    )

    test_target = self.make_target(
      'scala/classpath:scala_test',
      target_type=JUnitTests,
      sources=['com/example/Test.scala'],
      dependencies=[scala_target]
    )

    with temporary_dir() as tmp_dir:
      invalid_targets = [java_target, scala_target, scala_dep, test_target]
      task = self.create_task_with_target_roots(
        target_roots=[java_target, scala_target, test_target]
      )

      jobs = task._create_compile_jobs(
        compile_contexts=self.create_compile_contexts(invalid_targets, task, tmp_dir),
        invalid_targets=invalid_targets,
        invalid_vts=self.wrap_in_vts(invalid_targets),
        classpath_product=None)

      dependee_graph = self.construct_dependee_graph_str(jobs, task)

      self.assertEqual(dedent("""
                     zinc(java/classpath:java_lib) -> {}
                     rsc(scala/classpath:scala_lib) -> {
                       zinc_against_rsc(scala/classpath:scala_lib)
                     }
                     zinc_against_rsc(scala/classpath:scala_lib) -> {
                       zinc(scala/classpath:scala_test)
                     }
                     rsc(scala/classpath:scala_dep) -> {
                       rsc(scala/classpath:scala_lib),
                       zinc_against_rsc(scala/classpath:scala_lib),
                       zinc_against_rsc(scala/classpath:scala_dep)
                     }
                     zinc_against_rsc(scala/classpath:scala_dep) -> {
                       zinc(java/classpath:java_lib),
                       zinc(scala/classpath:scala_test)
                     }
                     zinc(scala/classpath:scala_test) -> {}""").strip(),
        dependee_graph)

  def test_scala_lib_with_java_sources_not_passed_to_rsc(self):
    self.init_dependencies_for_scala_libraries()

    java_target = self.make_target(
      'java/classpath:java_lib',
      target_type=JavaLibrary,
      sources=['com/example/Foo.java'],
      dependencies=[]
    )
    scala_target_direct_java_sources = self.make_target(
      'scala/classpath:scala_with_direct_java_sources',
      target_type=ScalaLibrary,
      sources=['com/example/Foo.scala', 'com/example/Bar.java'],
      dependencies=[]
    )
    scala_target_indirect_java_sources = self.make_target(
      'scala/classpath:scala_with_indirect_java_sources',
      target_type=ScalaLibrary,
      java_sources=['java/classpath:java_lib'],
      sources=['com/example/Foo.scala'],
      dependencies=[]
    )

    with temporary_dir() as tmp_dir:
      invalid_targets = [
        java_target,
        scala_target_direct_java_sources,
        scala_target_indirect_java_sources]
      task = self.create_task_with_target_roots(
        target_roots=[scala_target_indirect_java_sources, scala_target_direct_java_sources]
      )

      jobs = task._create_compile_jobs(
        compile_contexts=self.create_compile_contexts(invalid_targets, task, tmp_dir),
        invalid_targets=invalid_targets,
        invalid_vts=[LightWeightVTS(t) for t in invalid_targets],
        classpath_product=None)

      dependee_graph = self.construct_dependee_graph_str(jobs, task)

      self.assertEqual(dedent("""
                     zinc(java/classpath:java_lib) -> {}
                     zinc(scala/classpath:scala_with_direct_java_sources) -> {}
                     zinc(scala/classpath:scala_with_indirect_java_sources) -> {}""").strip(),
        dependee_graph)

  def test_desandbox_fn(self):
    # TODO remove this after https://github.com/scalameta/scalameta/issues/1791 is released
    desandbox = _create_desandboxify_fn(['.pants.d/cool/beans.*', '.pants.d/c/r/c/.*'])
    self.assertEqual(desandbox('/some/path/.pants.d/cool/beans'), '.pants.d/cool/beans')
    self.assertEqual(desandbox('/some/path/.pants.d/c/r/c/beans'), '.pants.d/c/r/c/beans')
    self.assertEqual(desandbox(
      '/some/path/.pants.d/exec-location/.pants.d/c/r/c/beans'),
      '.pants.d/c/r/c/beans')
    self.assertEqual(desandbox('/some/path/outside/workdir'), '/some/path/outside/workdir')
    # NB ensure that a path outside the workdir that partially matches won't be truncated
    self.assertEqual(desandbox('/some/path/outside/workdir.pants.d/cool/beans/etc'), '/some/path/outside/workdir.pants.d/cool/beans/etc')
    self.assertEqual(desandbox(None), None)
    # ensure that temp workdirs are discovered relative to the buildroot
    desandbox = _create_desandboxify_fn(['.pants.d/tmp.pants.d/cool/beans', '.pants.d/tmp.pants.d/c/r/c'])
    self.assertEqual(desandbox('/some/path/.pants.d/tmp.pants.d/cool/beans'), '.pants.d/tmp.pants.d/cool/beans')
    self.assertEqual(desandbox('/some/path/.pants.d/exec-location/.pants.d/tmp.pants.d/cool/beans'),
                               '.pants.d/tmp.pants.d/cool/beans')

  def construct_dependee_graph_str(self, jobs, task):
    exec_graph = ExecutionGraph(jobs, task.get_options().print_exception_stacktrace)
    dependee_graph = exec_graph.format_dependee_graph()
    print(dependee_graph)
    return dependee_graph

  def wrap_in_vts(self, invalid_targets):
    return [LightWeightVTS(t) for t in invalid_targets]

  def init_dependencies_for_scala_libraries(self):
    init_subsystem(
      ScalaPlatform,
      {
        ScalaPlatform.options_scope: {
          'version': 'custom',
          'suffix_version': '2.12',
        }
      }
    )
    self.make_target(
      '//:scala-library',
      target_type=JarLibrary,
      jars=[JarDependency(org='com.example', name='scala', rev='0.0.0')]
    )

  def create_task_with_target_roots(self, target_roots):
    context = self.context(target_roots=target_roots)
    self.init_products(context)
    task = self.create_task(context)
    # tried for options, but couldn't get it to reconfig
    task._size_estimator = lambda srcs: 0
    return task

  def init_products(self, context):
    context.products.get_data('compile_classpath', ClasspathProducts.init_func(self.pants_workdir))
    context.products.get_data('runtime_classpath', ClasspathProducts.init_func(self.pants_workdir))

  def create_compile_contexts(self, invalid_targets, task, tmp_dir):
    return {target: task.create_compile_context(target, os.path.join(tmp_dir, target.id))
      for target in invalid_targets}
