# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class WorkUnitLabelTest(PantsRunIntegrationTest):
    """This tests whether workunit label will appear in the log.

    The pants run itself is going to fail due to non existent main class when invoking java, but the
    point is to check whether certain label gets printed out.
    """

    load_plugin_cmdline = [
        f'--pythonpath={Path.cwd().joinpath("tests", "python")}',
        "--backend-packages=pants_test.logging.data",
    ]

    def test_workunit_no_label_ignore(self):
        pants_run = self.run_pants([*self.load_plugin_cmdline, "run-workunit-label-test"])
        self.assert_failure(pants_run)
        self.assertIn("[non-existent-main-class]", pants_run.stdout_data)

    def test_workunit_label_ignore(self):
        pants_run = self.run_pants(
            [*self.load_plugin_cmdline, "run-workunit-label-test", "--ignore-label"]
        )
        self.assert_failure(pants_run)
        self.assertNotIn("[non-existent-main-class]", pants_run.stdout_data)
