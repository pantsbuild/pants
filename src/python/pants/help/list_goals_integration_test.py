# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_integration_test import PantsIntegrationTest


class TestListGoalsIntegration(PantsIntegrationTest):
    def test_goals(self) -> None:
        pants_run = self.run_pants(["goals"])
        pants_run.assert_success()
        assert "to get help for a particular goal" in pants_run.stdout
        # Spot check a few core goals.
        for goal in ["filedeps", "list", "roots", "validate"]:
            assert goal in pants_run.stdout

    def test_only_show_implemented_goals(self) -> None:
        # Some core goals, such as `./pants test`, require downstream implementations to work
        # properly. We should only show those goals when an implementation is provided.
        goals_that_need_implementation = ["binary", "fmt", "lint", "run", "test"]
        command = ["--pants-config-files=[]", "goals"]

        not_implemented_run = self.run_pants(["--backend-packages=[]", *command])
        not_implemented_run.assert_success()
        for goal in goals_that_need_implementation:
            assert goal not in not_implemented_run.stdout

        implemented_run = self.run_pants(
            [
                "--backend-packages=['pants.backend.python', 'pants.backend.python.lint.isort']",
                *command,
            ],
        )
        implemented_run.assert_success()
        for goal in goals_that_need_implementation:
            assert goal in implemented_run.stdout

    def test_ignored_args(self) -> None:
        # Test that arguments (some of which used to be relevant) are ignored.
        pants_run = self.run_pants(["goals", "--all", "--graphviz", "--llama"])
        pants_run.assert_success()
        assert "to get help for a particular goal" in pants_run.stdout
