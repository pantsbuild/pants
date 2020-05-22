# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import glob
import os
import re
import subprocess

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_dir


class BuildLocalPythonDistributionsIntegrationTest(PantsRunIntegrationTest):
    @classmethod
    def use_pantsd_env_var(cls):
        """TODO(#7320): See the point about watchman."""
        return False

    hello_install_requires_dir = (
        "testprojects/src/python/python_distribution/hello_with_install_requires"
    )
    py_dist_test = "testprojects/tests/python/example_test/python_distribution"

    def _assert_nation_and_greeting(self, output, punctuation="!"):
        self.assertEquals(f"hello{punctuation}\nUnited States\n", output)

    def test_pydist_binary(self):
        with temporary_dir() as tmp_dir:
            pex = os.path.join(tmp_dir, "main_with_no_conflict.pex")
            command = [
                f"--pants-distdir={tmp_dir}",
                "binary",
                f"{self.hello_install_requires_dir}:main_with_no_conflict",
            ]
            pants_run = self.run_pants(command=command)
            self.assert_success(pants_run)
            # Check that the pex was built.
            self.assertTrue(os.path.isfile(pex))
            # Check that the pex runs.
            output = subprocess.check_output(pex).decode()
            self._assert_nation_and_greeting(output)
            # Check that we have exactly one wheel output.
            single_wheel_output = assert_single_element(glob.glob(os.path.join(tmp_dir, "*.whl")))
            self.assertRegex(
                os.path.basename(single_wheel_output),
                r"\A{}".format(re.escape("hello_with_install_requires-1.0.0+")),
            )

    def test_pydist_run(self):
        with temporary_dir() as tmp_dir:
            command = [
                f"--pants-distdir={tmp_dir}",
                "--quiet",
                "run",
                f"{self.hello_install_requires_dir}:main_with_no_conflict",
            ]
            pants_run = self.run_pants(command=command)
            self.assert_success(pants_run)
            # Check that text was properly printed to stdout.
            self._assert_nation_and_greeting(pants_run.stdout_data)

    def test_pydist_invalidation(self):
        """Test that the current version of a python_dist() is resolved after modifying its
        sources."""
        hello_run = f"{self.hello_install_requires_dir}:main_with_no_conflict"
        run_target = lambda: self.run_pants(command=["--quiet", "run", hello_run])

        unmodified_pants_run = run_target()
        self.assert_success(unmodified_pants_run)
        self._assert_nation_and_greeting(unmodified_pants_run.stdout_data)

        # Modify one of the source files for this target so that the output is different.
        py_source_file = os.path.join(self.hello_install_requires_dir, "hello_package/hello.py")
        with self.with_overwritten_file_content(py_source_file, lambda c: re.sub(b"!", b"?", c)):
            modified_pants_run = run_target()
            self.assert_success(modified_pants_run)
            self._assert_nation_and_greeting(modified_pants_run.stdout_data, punctuation="?")

    def test_pydist_test(self):
        with temporary_dir() as tmp_dir:
            command = [
                f"--pants-distdir={tmp_dir}",
                "test",
                self.py_dist_test,
            ]
            pants_run = self.run_pants(command=command)
            self.assert_success(pants_run)
            # Make sure that there is no wheel output when 'binary' goal is not invoked.
            self.assertEqual(0, len(glob.glob(os.path.join(tmp_dir, "*.whl"))))
