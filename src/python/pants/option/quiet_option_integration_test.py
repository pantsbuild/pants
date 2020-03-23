# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_file


class TestOptionsQuietIntegration(PantsRunIntegrationTest):
    def test_pants_default_quietness(self) -> None:
        pants_run = self.run_pants(["export"])
        self.assert_success(pants_run)
        json.loads(pants_run.stdout_data)

    def test_pants_no_quiet_cli(self) -> None:
        pants_run = self.run_pants(["--no-quiet", "export"])
        self.assert_success(pants_run)

        # Since pants progress will show up in stdout, therefore, json parsing should fail.
        with self.assertRaises(ValueError):
            json.loads(pants_run.stdout_data)

    def test_pants_no_quiet_env(self) -> None:
        pants_run = self.run_pants(["export"], extra_env={"PANTS_QUIET": "FALSE"})
        self.assert_success(pants_run)

        # Since pants progress will show up in stdout, therefore, json parsing should fail.
        with self.assertRaises(ValueError):
            json.loads(pants_run.stdout_data)

    def test_pants_no_quiet_output_file(self) -> None:
        with temporary_file() as f:
            pants_run = self.run_pants(["--no-quiet", "export", f"--output-file={f.name}"])
            self.assert_success(pants_run)

            json_string = f.read().decode()
            # Make sure the json is valid from the file read.
            json.loads(json_string)
            # Make sure json string does not appear in stdout.
            self.assertNotIn(json_string, pants_run.stdout_data)
