# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class DependenciesIntegrationTest(PantsRunIntegrationTest):
    def assert_deps(self, success, spec, *expected_deps):
        args = ["-q", "dependencies"] + [spec]
        pants_run = self.run_pants(args)
        if success:
            self.assert_success(pants_run)
            stdout_lines = pants_run.stdout_data.split("\n")
            for dep in expected_deps:
                self.assertIn(dep, stdout_lines)
        else:
            self.assert_failure(pants_run)
        return pants_run

    def test_synthetic(self):
        self.assert_deps(
            True,
            "examples/src/scala/org/pantsbuild/example/hello/welcome",
            "//:scala-library-synthetic",
        )

    def test_missing(self):
        self.assert_deps(False, "3rdparty:wait_seriously_there_is_a_library_named_that")

    def test_siblings(self):
        self.assert_deps(True, "3rdparty:")

    def test_descendants(self):
        self.assert_deps(True, "3rdparty::")
