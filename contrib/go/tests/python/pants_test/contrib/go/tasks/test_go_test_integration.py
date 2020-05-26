# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.dirutil import safe_open


class GoTestIntegrationTest(PantsRunIntegrationTest):
    def test_go_test_simple(self):
        args = ["test", "contrib/go/examples/src/go/libA"]
        pants_run = self.run_pants(args)
        self.assert_success(pants_run)
        # libA depends on libB, so both tests should be run.
        self.assertRegex(pants_run.stdout_data, r"ok\s+libA")
        self.assertRegex(pants_run.stdout_data, r"ok\s+libB")

        # Run a second time and see that they are cached.
        # TODO: this is better done with a unit test, and as noted in #7188, testing interaction with a
        # remote cache should probably be added somewhere.
        pants_run = self.run_pants(args)
        self.assert_success(pants_run)
        self.assertRegex(pants_run.stdout_data, r"contrib/go/examples/src/go/libA\s+\.+\s+SUCCESS")
        self.assertRegex(pants_run.stdout_data, r"contrib/go/examples/src/go/libB\s+\.+\s+SUCCESS")

        # Assert that we do *not* contain verbose output.
        self.assertNotIn("=== RUN   TestAdd", pants_run.stdout_data)
        self.assertNotIn("PASS", pants_run.stdout_data)

    def test_go_test_with_options(self):
        args = [
            "test.go",
            '--shlexed-build-and-test-flags=["-v"]',
            "contrib/go/examples/src/go/libA",
        ]
        pants_run = self.run_pants(args)
        self.assert_success(pants_run)
        self.assertRegex(pants_run.stdout_data, r"ok\s+libA")
        self.assertRegex(pants_run.stdout_data, r"ok\s+libB")

        # Ensure that more verbose output is presented.
        self.assertIn("=== RUN   TestAdd", pants_run.stdout_data)
        self.assertIn("PASS", pants_run.stdout_data)

    def test_go_test_unstyle(self):
        with self.temporary_sourcedir() as srcdir:
            lib_unstyle_relpath = "src/go/libUnstyle"
            lib_unstyle_dir = os.path.join(srcdir, lib_unstyle_relpath)
            with safe_open(os.path.join(lib_unstyle_dir, "unstyle.go"), "w") as fp:
                # NB: Go format violating indents below.
                fp.write(
                    dedent(
                        """
                        package libUnstyle

                        func Speak() {
                          println("Hello from libUnstyle!")
                          println("Bye from libUnstyle!")
                        }

                        func Add(a int, b int) int {
                        return a + b
                        }
                        """
                    ).strip()
                )
            with safe_open(os.path.join(lib_unstyle_dir, "BUILD"), "w") as fp:
                fp.write("go_library()")

            args = ["compile", "lint", lib_unstyle_dir]
            pants_run = self.run_pants(args)
            self.assert_failure(pants_run)

            args = ["compile", "lint", "--gofmt-skip", lib_unstyle_dir]
            pants_run = self.run_pants(args)
            self.assert_success(pants_run)
