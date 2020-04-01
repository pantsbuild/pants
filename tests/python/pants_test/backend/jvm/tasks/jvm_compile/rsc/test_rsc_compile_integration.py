# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants_test.backend.jvm.tasks.jvm_compile.rsc.rsc_compile_integration_base import (
    RscCompileIntegrationBase,
    ensure_compile_rsc_execution_strategy,
)


class RscCompileIntegration(RscCompileIntegrationBase):
    @pytest.mark.skip(reason="flaky: https://github.com/pantsbuild/pants/issues/7856")
    @ensure_compile_rsc_execution_strategy(RscCompileIntegrationBase.rsc_and_zinc)
    def test_basic_binary(self):
        self._testproject_compile("mutual", "bin", "A")

    @ensure_compile_rsc_execution_strategy(
        RscCompileIntegrationBase.rsc_and_zinc,
        PANTS_COMPILE_RSC_SCALA_WORKFLOW_OVERRIDE="zinc-only",
    )
    def test_workflow_override(self):
        self._testproject_compile("mutual", "bin", "A", outline_result=False)

    @ensure_compile_rsc_execution_strategy(RscCompileIntegrationBase.rsc_and_zinc)
    def test_executing_multi_target_binary(self):
        pants_run = self.do_command("run", "examples/src/scala/org/pantsbuild/example/hello/exe")
        self.assertIn("Hello, Resource World!", pants_run.stdout_data)

    @pytest.mark.skip(reason="flaky: https://github.com/pantsbuild/pants/issues/8679")
    @ensure_compile_rsc_execution_strategy(RscCompileIntegrationBase.rsc_and_zinc)
    def test_java_with_transitive_exported_scala_dep(self):
        self.do_command(
            "compile",
            "testprojects/src/scala/org/pantsbuild/testproject/javadepsonscalatransitive:java-in-different-package",
        )

    @ensure_compile_rsc_execution_strategy(RscCompileIntegrationBase.rsc_and_zinc)
    def test_java_sources(self):
        self.do_command("compile", "testprojects/src/scala/org/pantsbuild/testproject/javasources")

    @ensure_compile_rsc_execution_strategy(RscCompileIntegrationBase.rsc_and_zinc)
    def test_node_dependencies(self):
        self.do_command(
            "compile", "contrib/node/examples/src/java/org/pantsbuild/testproject/jsresources"
        )

    def test_rsc_hermetic_jvm_options(self):
        self._test_hermetic_jvm_options(self.rsc_and_zinc)
