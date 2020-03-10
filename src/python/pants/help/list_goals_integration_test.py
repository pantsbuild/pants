# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class TestListGoalsIntegration(PantsRunIntegrationTest):
    def test_goals(self) -> None:
        command = ["--v1", "--v2", "goals"]
        pants_run = self.run_pants(command=command)
        self.assert_success(pants_run)
        assert "to get help for a particular goal" in pants_run.stdout_data
        # Spot check a few core goals.
        for goal in ["filedeps", "list", "roots", "validate"]:
            assert goal in pants_run.stdout_data

    def test_only_show_implemented_goals(self) -> None:
        # Some core goals, such as `./pants test`, require downstream implementations to work
        # properly. We should only show those goals when an implementation is provided.
        goals_that_need_implementation = ["binary", "fmt", "lint", "run", "test"]
        command = ["--pants-config-files=[]", "--no-v1", "--v2", "goals"]

        not_implemented_run = self.run_pants(command)
        self.assert_success(not_implemented_run)
        for goal in goals_that_need_implementation:
            assert goal not in not_implemented_run.stdout_data

        implemented_run = self.run_pants(
            [
                "--backend-packages2=['pants.backend.python', 'pants.backend.python.lint.isort']",
                *command,
            ],
        )
        self.assert_success(implemented_run)
        for goal in goals_that_need_implementation:
            assert goal in implemented_run.stdout_data

    def test_ignored_args(self) -> None:
        # Test that arguments (some of which used to be relevant) are ignored.
        command = ["goals", "--all", "--graphviz", "--llama"]
        pants_run = self.run_pants(command=command)
        self.assert_success(pants_run)
        assert "to get help for a particular goal" in pants_run.stdout_data
