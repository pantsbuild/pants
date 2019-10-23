# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants_test.backend.jvm.tasks.jvm_compile.rsc.rsc_compile_integration_base import (
  RscCompileIntegrationBase,
  ensure_compile_rsc_execution_strategy,
)


class RscCompileIntegration(RscCompileIntegrationBase):

  @ensure_compile_rsc_execution_strategy(RscCompileIntegrationBase.rsc_and_zinc)
  def test_basic_binary(self):
    with self.do_command_yielding_workdir('compile', 'testprojects/src/scala/org/pantsbuild/testproject/mutual:bin') as pants_run:
      zinc_compiled_classfile = os.path.join(
        pants_run.workdir,
        'compile/rsc/current/testprojects.src.scala.org.pantsbuild.testproject.mutual.mutual/current/zinc',
        'classes/org/pantsbuild/testproject/mutual/A.class')
      self.assert_is_file(zinc_compiled_classfile)
      rsc_header_jar = os.path.join(
        pants_run.workdir,
        'compile/rsc/current/testprojects.src.scala.org.pantsbuild.testproject.mutual.mutual/current/rsc',
        'm.jar')
      self.assert_is_file(rsc_header_jar)

  @ensure_compile_rsc_execution_strategy(
    RscCompileIntegrationBase.rsc_and_zinc,
    PANTS_WORKFLOW_OVERRIDE="zinc-only")
  def test_workflow_override(self):
    with self.do_command_yielding_workdir('compile', 'testprojects/src/scala/org/pantsbuild/testproject/mutual:bin') as pants_run:
      zinc_compiled_classfile = os.path.join(
        pants_run.workdir,
        'compile/rsc/current/testprojects.src.scala.org.pantsbuild.testproject.mutual.mutual/current/zinc',
        'classes/org/pantsbuild/testproject/mutual/A.class')
      self.assert_is_file(zinc_compiled_classfile)
      rsc_header_jar = os.path.join(
        pants_run.workdir,
        'compile/rsc/current/testprojects.src.scala.org.pantsbuild.testproject.mutual.mutual/current/rsc',
        'm.jar')
      self.assert_is_not_file(rsc_header_jar)

  @ensure_compile_rsc_execution_strategy(RscCompileIntegrationBase.rsc_and_zinc)
  def test_executing_multi_target_binary(self):
    pants_run = self.do_command('run', 'examples/src/scala/org/pantsbuild/example/hello/exe')
    self.assertIn('Hello, Resource World!', pants_run.stdout_data)

  @ensure_compile_rsc_execution_strategy(RscCompileIntegrationBase.rsc_and_zinc)
  def test_java_with_transitive_exported_scala_dep(self):
    self.do_command('compile', 'testprojects/src/scala/org/pantsbuild/testproject/javadepsonscalatransitive:java-in-different-package')

  @ensure_compile_rsc_execution_strategy(RscCompileIntegrationBase.rsc_and_zinc)
  def test_java_sources(self):
    self.do_command('compile', 'testprojects/src/scala/org/pantsbuild/testproject/javasources')

  @ensure_compile_rsc_execution_strategy(RscCompileIntegrationBase.rsc_and_zinc)
  def test_node_dependencies(self):
    self.do_command('compile', 'contrib/node/examples/src/java/org/pantsbuild/testproject/jsresources')

  def test_rsc_hermetic_jvm_options(self):
    self._test_hermetic_jvm_options(self.rsc_and_zinc)
