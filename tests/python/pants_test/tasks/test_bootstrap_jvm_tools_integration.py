# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_dir


class BootstrapJvmToolsIntegrationTest(PantsRunIntegrationTest):
    def test_zinc_tool_reuse_between_scala_and_java(self):
        with temporary_dir() as artifact_cache:
            bootstrap_args = [
                "bootstrap.bootstrap-jvm-tools",
                f"--cache-write-to=['{artifact_cache}']",
                f"--cache-read-from=['{artifact_cache}']",
            ]

            # Scala compilation should bootstrap and shade zinc.
            args = bootstrap_args + ["compile", "examples/src/scala/org/pantsbuild/example/hello"]
            pants_run = self.run_pants(args)
            self.assert_success(pants_run)
            self.assertTrue("[shade-compiler-interface]" in pants_run.stdout_data)

            # The shaded zinc artifact should be cached, so zinc-based Java compilation
            # should reuse it instead of bootstrapping and shading again, even after clean-all.
            pants_run = self.run_pants(
                bootstrap_args
                + ["clean-all", "compile", "examples/src/java/org/pantsbuild/example/hello/simple"]
            )
            self.assert_success(pants_run)
            self.assertFalse("[shade-compiler-interface]" in pants_run.stdout_data)
