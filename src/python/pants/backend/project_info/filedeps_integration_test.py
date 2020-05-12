# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class FiledepsIntegrationTest(PantsRunIntegrationTest):
    def assert_filedeps(
        self, *, filedeps_options: Optional[List[str]] = None, expected_entries: List[str]
    ) -> None:
        args = [
            "filedeps2",
            "--transitive",
            *(filedeps_options or []),
            "examples/src/scala/org/pantsbuild/example/hello/exe:exe",
            "examples/src/scala/org/pantsbuild/example/hello/welcome:welcome",
        ]
        pants_run = self.run_pants(args)
        self.assert_success(pants_run)
        self.assertEqual(pants_run.stdout_data.strip(), "\n".join(expected_entries))

    def test_filedeps_basic(self):
        self.assert_filedeps(
            expected_entries=[
                "examples/src/java/org/pantsbuild/example/hello/greet/BUILD",
                "examples/src/java/org/pantsbuild/example/hello/greet/Greeting.java",
                "examples/src/resources/org/pantsbuild/example/hello/BUILD",
                "examples/src/resources/org/pantsbuild/example/hello/world.txt",
                "examples/src/scala/org/pantsbuild/example/hello/exe/BUILD",
                "examples/src/scala/org/pantsbuild/example/hello/exe/Exe.scala",
                "examples/src/scala/org/pantsbuild/example/hello/welcome/BUILD",
                "examples/src/scala/org/pantsbuild/example/hello/welcome/Welcome.scala",
            ]
        )

    def test_filedeps_globs(self):
        self.assert_filedeps(
            filedeps_options=["--globs"],
            expected_entries=[
                "examples/src/java/org/pantsbuild/example/hello/greet/*.java",
                "examples/src/java/org/pantsbuild/example/hello/greet/BUILD",
                "examples/src/resources/org/pantsbuild/example/hello/BUILD",
                "examples/src/resources/org/pantsbuild/example/hello/world.txt",
                "examples/src/scala/org/pantsbuild/example/hello/exe/BUILD",
                "examples/src/scala/org/pantsbuild/example/hello/exe/Exe.scala",
                "examples/src/scala/org/pantsbuild/example/hello/welcome/*.scala",
                "examples/src/scala/org/pantsbuild/example/hello/welcome/BUILD",
            ],
        )
