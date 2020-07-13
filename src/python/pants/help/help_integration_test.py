# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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
        # Spot check to see that scope headings are printed
        assert "`pytest` subsystem options" in pants_run.stdout_data
        # Spot check to see that full args for all options are printed
        assert "--[no-]test-debug" in pants_run.stdout_data
        # Spot check to see that subsystem options are printing
        assert "--pytest-version" in pants_run.stdout_data

    def test_help_all_advanced(self):
        command = ["--help-all", "--help-advanced"]
        pants_run = self.run_pants(command=command)
        self.assert_success(pants_run)
        # Spot check to see that scope headings are printed even for advanced options
        assert "`pytest` subsystem options" in pants_run.stdout_data
        assert "`pytest` subsystem advanced options" in pants_run.stdout_data
        # Spot check to see that full args for all options are printed
        assert "--[no-]test-debug" in pants_run.stdout_data
        # Spot check to see that subsystem options are printing
        assert "--pytest-version" in pants_run.stdout_data
        # Spot check to see that advanced subsystem options are printing
        assert "--pytest-timeout-default" in pants_run.stdout_data
