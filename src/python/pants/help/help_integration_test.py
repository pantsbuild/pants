# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class TestHelpIntegration(PantsRunIntegrationTest):
    def test_help(self):
        command = ["help"]
        pants_run = self.run_pants(command=command)
        self.assert_success(pants_run)
        assert "Usage:" in pants_run.stdout_data
        # spot check to see that a public global option is printed
        assert "--level" in pants_run.stdout_data
        assert "Global options" in pants_run.stdout_data

    def test_help_advanced(self):
        command = ["help-advanced"]
        pants_run = self.run_pants(command=command)
        self.assert_success(pants_run)
        assert "Global advanced options" in pants_run.stdout_data
        # Spot check to see that a global advanced option is printed
        assert "--pants-bootstrapdir" in pants_run.stdout_data

    def test_help_all(self):
        command = ["help-all"]
        pants_run = self.run_pants(command=command)
        self.assert_success(pants_run)
        all_help = json.loads(pants_run.stdout_data)

        # Spot check the data.
        assert "name_to_goal_info" in all_help
        assert "test" in all_help["name_to_goal_info"]

        assert "scope_to_help_info" in all_help
        assert "" in all_help["scope_to_help_info"]
        assert "pytest" in all_help["scope_to_help_info"]
        assert len(all_help["scope_to_help_info"]["pytest"]["basic"]) > 0
