# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from pathlib import Path

from pants.base.build_environment import get_buildroot
from pants.option.scope import GLOBAL_SCOPE_CONFIG_SECTION
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class RunnerIntegrationTest(PantsRunIntegrationTest):
    """Test logic performed in PantsRunner."""

    def test_warning_filter(self):
        # We load the testprojects pants-plugins to get some testing tasks and subsystems.
        cmdline = [
            "--no-pantsd",
            f"--pythonpath=+['{Path(get_buildroot(), 'testprojects/pants-plugins/src/python')}']",
            "--backend-packages=+['test_pants_plugin']",
            # This task will always emit a DeprecationWarning.
            "deprecation-warning-task",
        ]

        warning_run = self.run_pants(cmdline)
        self.assert_success(warning_run)
        self.assertRegex(
            warning_run.stderr_data,
            "\\[WARN\\].*DeprecationWarning: DEPRECATED: This is a test warning!",
        )

        non_warning_run = self.run_pants(
            cmdline,
            config={
                GLOBAL_SCOPE_CONFIG_SECTION: {
                    # NB: We do *not* include the exclamation point at the end, which tests that the regexps
                    # match from the beginning of the warning string, and don't require matching the entire
                    # string! We also lowercase the message to check that they are matched case-insensitively.
                    "ignore_pants_warnings": ["deprecated: this is a test warning"]
                },
            },
        )
        self.assert_success(non_warning_run)
        self.assertNotIn("test warning", non_warning_run.stderr_data)

    def test_parent_build_id_set_only_for_pants_runs_called_by_other_pants_runs(self):
        with self.temporary_workdir() as workdir:
            command = [
                "run",
                "testprojects/src/python/nested_runs",
                "--",
                workdir,
            ]
            result = self.run_pants_with_workdir(command, workdir,)
            self.assert_success(result)

            run_tracker_dir = os.path.join(workdir, "run-tracker")
            self.assertTrue(
                os.path.isdir(run_tracker_dir), f"dir path {run_tracker_dir} does not exist!"
            )
            run_tracker_sub_dirs = (
                os.path.join(run_tracker_dir, dir_name)
                for dir_name in os.listdir(run_tracker_dir)
                if dir_name != "latest"
            )
            for run_tracker_sub_dir in run_tracker_sub_dirs:
                info_path = os.path.join(run_tracker_sub_dir, "info")
                self.assert_is_file(info_path)
                with open(info_path, "r") as info_f:
                    lines = dict(line.split(": ", 1) for line in info_f.readlines())
                    if "goals" in lines["cmd_line"]:
                        self.assertIn("parent_build_id", lines)
                    else:
                        self.assertNotIn("parent_build_id", lines)
