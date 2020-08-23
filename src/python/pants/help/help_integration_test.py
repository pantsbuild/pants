# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json

from pants.testutil.pants_integration_test import run_pants


def test_help() -> None:
    pants_run = run_pants(["help"])
    pants_run.assert_success()
    assert "Usage:" in pants_run.stdout
    # spot check to see that a public global option is printed
    assert "--level" in pants_run.stdout
    assert "Global options" in pants_run.stdout


def test_help_advanced() -> None:
    pants_run = run_pants(["help-advanced"])
    pants_run.assert_success()
    assert "Global advanced options" in pants_run.stdout
    # Spot check to see that a global advanced option is printed
    assert "--pants-bootstrapdir" in pants_run.stdout


def test_help_all() -> None:
    pants_run = run_pants(["--backend-packages=pants.backend.python", "help-all"])
    pants_run.assert_success()
    all_help = json.loads(pants_run.stdout)

    # Spot check the data.
    assert "name_to_goal_info" in all_help
    assert "test" in all_help["name_to_goal_info"]

    assert "scope_to_help_info" in all_help
    assert "" in all_help["scope_to_help_info"]
    assert "pytest" in all_help["scope_to_help_info"]
    assert len(all_help["scope_to_help_info"]["pytest"]["basic"]) > 0
