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

    def test_stats_local_json_file_v1(self):
        with temporary_file_path() as tmpfile:
            pants_run = self.run_pants(
                [
                    "list",
                    "test",
                    f"--run-tracker-stats-local-json-file={tmpfile}",
                    "--run-tracker-stats-version=1",
                    "--reporting-zipkin-trace-v2",
                    '--run-tracker-stats-option-scopes-to-record=["GLOBAL", "GLOBAL^time", "compile.rsc^capture_classpath"]',
                    "testprojects/src/java/org/pantsbuild/testproject/extra_jvm_options::",
                    "testprojects/src/java/org/pantsbuild/testproject/unicode/main",
                ]
            )
            self.assert_success(pants_run)

            with open(tmpfile, "r") as fp:
                stats_json = json.load(fp)
                self.assertIn("outcomes", stats_json)
                self.assertEqual(stats_json["outcomes"]["main:test"], "SUCCESS")
                self.assertIn("artifact_cache_stats", stats_json)
                self.assertIn("run_info", stats_json)

                computed_goals = stats_json["run_info"]["computed_goals"]
                self.assertIsInstance(computed_goals, list)

                # Explicit v1 goal on the command line:
                self.assertIn("test", stats_json["run_info"]["computed_goals"])
                # v1 goal implied by dependencies between goals:
                self.assertIn("compile", stats_json["run_info"]["computed_goals"])
                # Check that v2 goals are included:
                self.assertIn("list", stats_json["run_info"]["computed_goals"])

                # Expanded to canonical form, but not expanded to its actual targets.
                self.assertEquals(
                    [
                        "testprojects/src/java/org/pantsbuild/testproject/extra_jvm_options::",
                        "testprojects/src/java/org/pantsbuild/testproject/unicode/main:main",
                    ],
                    stats_json["run_info"]["specs_from_command_line"],
                )

                self.assertIn("self_timings", stats_json)
                self.assertIn("cumulative_timings", stats_json)
                self.assertIn("pantsd_stats", stats_json)
                self.assertIn("recorded_options", stats_json)
                self.assertIn("GLOBAL", stats_json["recorded_options"])
                self.assertNotIn("engine_workunits", stats_json["pantsd_stats"])
                self.assertIs(stats_json["recorded_options"]["GLOBAL"]["time"], False)
                self.assertEqual(stats_json["recorded_options"]["GLOBAL"]["level"], "info")
                self.assertIs(stats_json["recorded_options"]["GLOBAL^time"], False)
                self.assertEqual(
                    stats_json["recorded_options"]["compile.rsc^capture_classpath"], True
                )

    def test_stats_local_json_file_v2(self):
        with temporary_file_path() as tmpfile:
            pants_run = self.run_pants(
                [
                    "test",
                    f"--run-tracker-stats-local-json-file={tmpfile}",
                    "--run-tracker-stats-version=2",
                    "--reporting-zipkin-trace-v2",
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
