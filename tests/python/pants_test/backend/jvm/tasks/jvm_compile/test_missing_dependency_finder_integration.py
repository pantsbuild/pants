# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re

import pytest

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


@pytest.mark.skip(reason="times out")
class MissingDependencyFinderIntegrationTest(PantsRunIntegrationTest):
    def test_missing_deps_found(self):
        target = "testprojects/src/java/org/pantsbuild/testproject/missingjardepswhitelist:missingjardepswhitelist"
        run = self.run_pants(["compile", target, "--compile-rsc-suggest-missing-deps"])
        self.assert_failure(run)
        self.assertTrue(
            re.search(
                "Found the following deps from target's transitive dependencies "
                "that provide the missing classes:.*"
                "com.google.common.io.Closer: 3rdparty:guava",
                run.stdout_data,
                re.DOTALL,
            )
        )
        self.assertTrue(
            re.search(
                "please add the following to the dependencies of.*" "'3rdparty:guava',",
                run.stdout_data,
                re.DOTALL,
            )
        )
        self.assertFalse(re.search("buildozer", run.stdout_data, re.DOTALL))

    def test_missing_deps_found_buildozer(self):
        target = "testprojects/src/java/org/pantsbuild/testproject/missingjardepswhitelist:missingjardepswhitelist"
        run = self.run_pants(
            [
                "compile",
                target,
                "--compile-rsc-suggest-missing-deps",
                "--compile-rsc-buildozer=path/to/buildozer",
            ]
        )
        self.assert_failure(run)
        self.assertTrue(
            re.search(
                "\n *path/to/buildozer 'add dependencies 3rdparty:guava' " + target,
                run.stdout_data,
                re.DOTALL,
            )
        )

    def test_missing_deps_not_found(self):
        target = (
            "testprojects/src/java/org/pantsbuild/testproject/dummies:compilation_failure_target"
        )
        run = self.run_pants(["compile", target, "--compile-rsc-suggest-missing-deps", "-ldebug"])
        self.assert_failure(run)
        self.assertTrue(
            re.search(
                "Unable to find any deps from target's transitive dependencies "
                "that provide the following missing classes:.*"
                "System2.out",
                run.stdout_data,
                re.DOTALL,
            )
        )
