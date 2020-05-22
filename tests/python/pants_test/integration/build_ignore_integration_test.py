# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import tempfile

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class IgnorePatternsPantsIniIntegrationTest(PantsRunIntegrationTest):
    """Tests the functionality of the build_ignore_patterns option in pants.toml ."""

    @classmethod
    def use_pantsd_env_var(cls):
        """Some of the tests here expect to read the standard error after an intentional failure.

        However, when pantsd is enabled, these errors are logged to logs/exceptions.<pid>.log So
        stderr appears empty. (see #7320)
        """
        return False

    def test_build_ignore_patterns_pants_toml(self):
        target_path = "testprojects/src/java/org/pantsbuild/testproject/phrases"
        targets = [
            f"{target_path}:{target}"
            for target in ["ten-thousand", "once-upon-a-time", "lesser-of-two", "there-was-a-duck"]
        ]
        # NB: We glob against all of testprojects, but when ran with --chroot or V2 test runner, there
        # will only be a few testprojects actually there, specifically the ones declared in this test
        # file's BUILD entry. We use the glob, rather than the more precise `target_path`, because
        # `target_path` will no longer be valid once it gets ignored later in the test.
        testprojects_glob = "testprojects/::"

        def output_to_list(output_filename):
            with open(output_filename, "r") as results_file:
                return {line.rstrip() for line in results_file.readlines()}

        tempdir = tempfile.mkdtemp()
        tmp_output = os.path.join(tempdir, "minimize-output1.txt")
        run_result = self.run_pants(
            ["minimize", testprojects_glob, "--quiet", f"--minimize-output-file={tmp_output}"]
        )
        self.assert_success(run_result)
        results = output_to_list(tmp_output)
        for target in targets:
            self.assertIn(target, results)

        tmp_output = os.path.join(tempdir, "minimize-output2.txt")
        run_result = self.run_pants(
            ["minimize", testprojects_glob, "--quiet", f"--minimize-output-file={tmp_output}"],
            config={"DEFAULT": {"build_ignore": [target_path]}},
        )
        self.assert_success(run_result)
        results = output_to_list(tmp_output)
        for target in targets:
            self.assertNotIn(target, results)

    def test_build_ignore_dependency(self):
        run_result = self.run_pants(
            [
                "-q",
                "dependencies",
                "--transitive",
                "testprojects/tests/python/pants/constants_only::",
            ],
            config={"DEFAULT": {"build_ignore": ["testprojects/src/"]}},
        )

        self.assert_failure(run_result)
        # Error message complains dependency dir has no BUILD files.
        self.assertIn(
            "testprojects/src/thrift/org/pantsbuild/constants_only", run_result.stderr_data
        )

    def test_build_ignore_dependency_success(self):
        run_result = self.run_pants(
            [
                "-q",
                "dependencies",
                "--transitive",
                "testprojects/tests/python/pants/constants_only::",
            ],
            config={"DEFAULT": {"build_ignore": ["testprojects/src/java"]}},
        )

        self.assert_success(run_result)
        self.assertIn(
            "testprojects/tests/python/pants/constants_only:constants_only", run_result.stdout_data
        )
