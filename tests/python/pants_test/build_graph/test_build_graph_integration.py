# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class BuildGraphIntegrationTest(PantsRunIntegrationTest):
    @classmethod
    def use_pantsd_env_var(cls):
        """Some of the tests here expect to read the standard error after an intentional failure.

        However, when pantsd is enabled, these errors are logged to logs/exceptions.<pid>.log So
        stderr appears empty. (see #7320)
        """
        return False

    def test_cycle(self):
        prefix = "testprojects/src/java/org/pantsbuild/testproject"
        with self.file_renamed(os.path.join(prefix, "cycle1"), "TEST_BUILD", "BUILD"):
            with self.file_renamed(os.path.join(prefix, "cycle2"), "TEST_BUILD", "BUILD"):
                pants_run = self.run_pants(["compile", os.path.join(prefix, "cycle1")])
                self.assert_failure(pants_run)
                self.assertIn("cycle", pants_run.stderr_data)

    def test_banned_module_import(self):
        self.banned_import("testprojects/src/python/build_file_imports_module")

    def test_banned_function_import(self):
        self.banned_import("testprojects/src/python/build_file_imports_function")

    def banned_import(self, dir):
        with self.file_renamed(dir, "TEST_BUILD", "BUILD"):
            pants_run = self.run_pants(
                ["--build-file-imports=error", "run", f"{dir}:hello",],
                print_exception_stacktrace=False,
            )
            self.assert_failure(pants_run)
            assert f"Import used in {dir}/BUILD at line" in pants_run.stderr_data

    def test_warn_module_import(self):
        self.warn_import("testprojects/src/python/build_file_imports_module")

    def test_warn_function_import(self):
        self.warn_import("testprojects/src/python/build_file_imports_function")

    def warn_import(self, dir):
        with self.file_renamed(dir, "TEST_BUILD", "BUILD"):
            pants_run = self.run_pants(["--build-file-imports=warn", "run", f"{dir}:hello",])
            self.assert_success(pants_run)
            assert "Hello\n" in pants_run.stdout_data
            assert f"Import used in {dir}/BUILD at line" in pants_run.stderr_data

    def test_allowed_module_import(self):
        self.allowed_import("testprojects/src/python/build_file_imports_module")

    def test_allowed_function_import(self):
        self.allowed_import("testprojects/src/python/build_file_imports_function")

    def allowed_import(self, dir):
        with self.file_renamed(dir, "TEST_BUILD", "BUILD"):
            pants_run = self.run_pants(["--build-file-imports=allow", "run", f"{dir}:hello",])
        self.assert_success(pants_run)
        self.assertIn("Hello\n", pants_run.stdout_data)
