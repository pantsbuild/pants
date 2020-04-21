# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class DependeesIntegrationTest(PantsRunIntegrationTest):

    TARGET = "examples/src/scala/org/pantsbuild/example/hello/welcome"

    def run_dependees(self, *dependees_options):
        args = ["-q", "dependees", self.TARGET]
        args.extend(dependees_options)

        pants_run = self.run_pants(args)
        self.assert_success(pants_run)
        return pants_run.stdout_data.strip()

    def test_dependees_basic(self):
        pants_stdout = self.run_dependees()
        expected = {
            "examples/src/scala/org/pantsbuild/example/jvm_run:jvm-run-example-lib",
            "examples/src/scala/org/pantsbuild/example/hello/exe:exe",
            "examples/tests/scala/org/pantsbuild/example/hello/welcome:welcome",
        }
        actual = set(pants_stdout.split())
        self.assertEqual(expected, actual)

    def test_dependees_transitive(self):
        pants_stdout = self.run_dependees("--dependees-transitive")
        self.assertEqual(
            {
                "examples/src/scala/org/pantsbuild/example/jvm_run:jvm-run-example-lib",
                "examples/src/scala/org/pantsbuild/example/hello:hello",
                "examples/src/scala/org/pantsbuild/example/jvm_run:jvm-run-example",
                "examples/src/scala/org/pantsbuild/example/hello/exe:exe",
                "examples/tests/scala/org/pantsbuild/example/hello/welcome:welcome",
            },
            set(pants_stdout.split()),
        )

    def test_dependees_closed(self):
        pants_stdout = self.run_dependees("--dependees-closed")
        self.assertEqual(
            {
                "examples/src/scala/org/pantsbuild/example/hello/welcome:welcome",
                "examples/src/scala/org/pantsbuild/example/jvm_run:jvm-run-example-lib",
                "examples/src/scala/org/pantsbuild/example/hello/exe:exe",
                "examples/tests/scala/org/pantsbuild/example/hello/welcome:welcome",
            },
            set(pants_stdout.split()),
        )

    def test_dependees_json(self):
        pants_stdout = self.run_dependees("--dependees-output-format=json")
        self.assertEqual(
            dedent(
                """
                {
                    "examples/src/scala/org/pantsbuild/example/hello/welcome:welcome": [
                        "examples/src/scala/org/pantsbuild/example/hello/exe:exe",
                        "examples/src/scala/org/pantsbuild/example/jvm_run:jvm-run-example-lib",
                        "examples/tests/scala/org/pantsbuild/example/hello/welcome:welcome"
                    ]
                }"""
            ).lstrip("\n"),
            pants_stdout,
        )
