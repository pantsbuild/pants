# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.util.contextutil import temporary_dir
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


class JavacCompileIntegration(BaseCompileIT):
    def test_basic_binary(self):
        with temporary_dir() as cache_dir:
            config = {
                "cache.compile.javac": {"write_to": [cache_dir]},
                "jvm-platform": {"compiler": "javac"},
            }

            with self.temporary_workdir() as workdir:
                pants_run = self.run_pants_with_workdir(
                    [
                        "compile",
                        "testprojects/src/java/org/pantsbuild/testproject/publish/hello/main:",
                    ],
                    workdir,
                    config,
                )
                self.assert_success(pants_run)

    def test_basic_binary_hermetic(self):
        with temporary_dir() as cache_dir:
            config = {
                "cache.compile.javac": {"write_to": [cache_dir]},
                "jvm-platform": {"compiler": "javac"},
                "compile.javac": {"execution_strategy": "hermetic"},
            }

            with self.temporary_workdir() as workdir:
                pants_run = self.run_pants_with_workdir(
                    [
                        "compile",
                        "testprojects/src/java/org/pantsbuild/testproject/publish/hello/greet",
                    ],
                    workdir,
                    config,
                )
                self.assert_success(pants_run)
                path = os.path.join(
                    workdir,
                    "compile/javac/current/testprojects.src.java.org.pantsbuild.testproject.publish.hello.greet.greet/current",
                    "classes/org/pantsbuild/testproject/publish/hello/greet/Greeting.class",
                )
                self.assertTrue(os.path.exists(path))

    def test_apt_compile(self):
        for strategy in ("subprocess", "hermetic"):
            with self.do_test_compile(
                "testprojects/src/java/org/pantsbuild/testproject/annotation/processor",
                expected_files=[
                    "ResourceMappingProcessor.class",
                    "javax.annotation.processing.Processor",
                ],
                extra_args=[
                    "--jvm-platform-compiler=javac",
                    f"--compile-javac-execution-strategy={strategy}",
                ],
            ) as found:
                self.assertTrue(
                    self.get_only(found, "ResourceMappingProcessor.class").endswith(
                        "org/pantsbuild/testproject/annotation/processor/ResourceMappingProcessor.class"
                    )
                )

                # processor info file under classes/ dir
                processor_service_files = found["javax.annotation.processing.Processor"]
                # There should be only a per-target service info file.
                self.assertEqual(1, len(processor_service_files))
                processor_service_file = list(processor_service_files)[0]
                self.assertTrue(
                    processor_service_file.endswith(
                        "META-INF/services/javax.annotation.processing.Processor"
                    )
                )
                with open(processor_service_file, "r") as fp:
                    self.assertEqual(
                        "org.pantsbuild.testproject.annotation.processor.ResourceMappingProcessor",
                        fp.read().strip(),
                    )
