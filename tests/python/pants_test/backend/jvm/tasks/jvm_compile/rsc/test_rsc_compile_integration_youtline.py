# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants_test.backend.jvm.tasks.jvm_compile.rsc.rsc_compile_integration_base import (
  RscCompileIntegrationBase,
  ensure_compile_rsc_execution_strategy,
)


class RscCompileIntegration(RscCompileIntegrationBase):

  @ensure_compile_rsc_execution_strategy(RscCompileIntegrationBase.outline_and_zinc)
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
    RscCompileIntegrationBase.outline_and_zinc,
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

  def test_youtline_hermetic_jvm_options(self):
    self._test_hermetic_jvm_options(self.outline_and_zinc)
