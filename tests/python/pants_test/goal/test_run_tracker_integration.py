# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from pathlib import Path

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_file_path


class RunTrackerIntegrationTest(PantsRunIntegrationTest):

    load_plugin_cmdline = [
        f'--pythonpath={Path.cwd().joinpath("tests", "python")}',
        "--backend-packages=pants_test.goal.data",
    ]

    def test_stats_local_json_file_v2(self):
        with temporary_file_path() as tmpfile:
            pants_run = self.run_pants(
                [
                    "test",
                    f"--run-tracker-stats-local-json-file={tmpfile}",
                    "--run-tracker-stats-version=2",
                    "testprojects/src/java/org/pantsbuild/testproject/unicode/main",
                ]
            )
            self.assert_success(pants_run)

            with open(tmpfile, "r") as fp:
                stats_json = json.load(fp)
                self.assertIn("artifact_cache_stats", stats_json)
                self.assertIn("run_info", stats_json)
                self.assertIn("pantsd_stats", stats_json)
                self.assertIn("workunits", stats_json)
                self.assertNotIn("engine_workunits", stats_json["pantsd_stats"])

    def test_workunit_failure(self):
        pants_run = self.run_pants(
            [*self.load_plugin_cmdline, "run-dummy-workunit", "--no-success"]
        )
        # Make sure the task actually happens and of no exception.
        self.assertIn("[run-dummy-workunit]", pants_run.stdout_data)
        self.assertNotIn("Exception", pants_run.stderr_data)
        self.assert_failure(pants_run)

    def test_workunit_success(self):
        pants_run = self.run_pants([*self.load_plugin_cmdline, "run-dummy-workunit", "--success"])
        self.assert_success(pants_run)
