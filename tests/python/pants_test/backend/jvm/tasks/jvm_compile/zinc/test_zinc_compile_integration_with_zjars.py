# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT
from pants_test.backend.jvm.tasks.jvm_compile.zinc.zinc_compile_integration_base import (
    BaseZincCompileIntegrationTest,
)


class ZincCompileIntegrationWithZjars(BaseCompileIT, BaseZincCompileIntegrationTest):
    _EXTRA_TASK_ARGS = ["--compile-rsc-use-classpath-jars"]

    def test_classpath_includes_jars_when_use_jars_enabled(self):
        target_spec = "examples/src/java/org/pantsbuild/example/hello/main"
        classpath_filename = "examples.src.java.org.pantsbuild.example.hello.main.main-bin.txt"

        with self.do_test_compile(
            target_spec,
            expected_files=[classpath_filename],
            extra_args=["--compile-rsc-capture-classpath"],
        ) as found:

            found_classpath_file = self.get_only(found, classpath_filename)
            with open(found_classpath_file, "r") as f:
                contents = f.read()
                self.assertIn("z.jar", contents)
