# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class TestReportingIntegrationTest(PantsRunIntegrationTest, unittest.TestCase):
    def test_epilog_to_stderr(self) -> None:
        def run_test(quiet_flag: str) -> None:
            command = [
                "--time",
                quiet_flag,
                "bootstrap",
                "examples/src/python/example/hello::",
            ]
            pants_run = self.run_pants(command)
            self.assert_success(pants_run)
            self.assertIn("Cumulative Timings", pants_run.stderr_data)
            self.assertNotIn("Cumulative Timings", pants_run.stdout_data)

        run_test("--quiet")
        run_test("--no-quiet")
