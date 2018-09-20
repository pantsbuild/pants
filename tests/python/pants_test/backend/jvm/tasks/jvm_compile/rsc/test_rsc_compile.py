# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from textwrap import dedent

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.jvm_compile.execution_graph import ExecutionGraph
from pants.backend.jvm.tasks.jvm_compile.rsc.rsc_compile import RscCompile
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

  def test_metacp_job_scheduled_for_jar_library(self):
    # Init dependencies for scala library targets.
    init_subsystem(
      ScalaPlatform,
      {ScalaPlatform.options_scope: {
      'version': 'custom',
      'suffix_version': '2.12',
      }}
    )
    self.make_target(
      '//:scala-library',
      target_type=JarLibrary,
      jars=[JarDependency(org='com.example', name='scala', rev='0.0.0')]
    )

    jar_target = self.make_target(
      'java/classpath:jar_lib',
      target_type=JarLibrary,
      jars=[JarDependency(org='com.example', name='example', rev='0.0.0')]
    )

    java_target = self.make_target(
      'java/classpath:java_lib',
      target_type=JavaLibrary,
      sources=['com/example/Foo.java'],
      dependencies=[jar_target]
    )

    scala_target = self.make_target(
      'java/classpath:scala_lib',
      target_type=ScalaLibrary,
      sources=['com/example/Foo.scala'],
      dependencies=[jar_target]
    )

    context = self.context(target_roots=[jar_target])

    context.products.get_data('compile_classpath', ClasspathProducts.init_func(self.pants_workdir))
    context.products.get_data('runtime_classpath', ClasspathProducts.init_func(self.pants_workdir))

    task = self.create_task(context)
    # tried for options, but couldn't get it to reconfig
    task._size_estimator = lambda srcs: 0
    with temporary_dir() as tmp_dir:
      compile_contexts = {target: task.create_compile_context(target, os.path.join(tmp_dir, target.id))
                          for target in [jar_target, java_target, scala_target]}

      invalid_targets = [java_target, scala_target, jar_target]

      jobs = task._create_compile_jobs(compile_contexts,
                                       invalid_targets,
                                       invalid_vts=[LightWeightVTS(t) for t in invalid_targets],
                                       classpath_product=None)

      exec_graph = ExecutionGraph(jobs, task.get_options().print_exception_stacktrace)
      dependee_graph = exec_graph.format_dependee_graph()

      self.assertEqual(dedent("""
                     compile_against_rsc(java/classpath:java_lib) -> {}
                     rsc(java/classpath:scala_lib) -> {
                       compile_against_rsc(java/classpath:scala_lib)
                     }
                     compile_against_rsc(java/classpath:scala_lib) -> {}
                     metacp(java/classpath:jar_lib) -> {
                       rsc(java/classpath:scala_lib)
                     }""").strip(),
        dependee_graph)
