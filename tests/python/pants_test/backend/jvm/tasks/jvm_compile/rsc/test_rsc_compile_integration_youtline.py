# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants_test.backend.jvm.tasks.jvm_compile.rsc.rsc_compile_integration_base import (
  RscCompileIntegrationBase,
  ensure_compile_rsc_execution_strategy,
)


class RscCompileIntegrationYoutline(RscCompileIntegrationBase):

  @ensure_compile_rsc_execution_strategy(RscCompileIntegrationBase.outline_and_zinc)
  def test_basic_binary(self):
    self._testproject_compile("mutual", "bin", "A")

  @ensure_compile_rsc_execution_strategy(RscCompileIntegrationBase.outline_and_zinc)
  def test_public_inference_allowed(self):
    self._testproject_compile("public_inference", "public_inference", "PublicInference", "--compile-rsc-allow-public-inference")
      
  @ensure_compile_rsc_execution_strategy(RscCompileIntegrationBase.outline_and_zinc)
  def test_public_inference_disallowed(self):
    self._testproject_compile("public_inference", "public_inference", "PublicInference", success=False, zinc_result=True, outline_result=False)

  @ensure_compile_rsc_execution_strategy(
    RscCompileIntegrationBase.outline_and_zinc,
    PANTS_WORKFLOW_OVERRIDE="zinc-only")
  def test_workflow_override(self):
    self._testproject_compile("mutual", "bin", "A", outline_result=False)

  def test_youtline_hermetic_jvm_options(self):
    self._test_hermetic_jvm_options(self.outline_and_zinc)
