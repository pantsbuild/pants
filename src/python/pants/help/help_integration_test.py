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


def test_unknown_goal() -> None:
    pants_run = run_pants(["testx"],)
    pants_run.assert_failure()
    assert "Unknown goal: testx" in pants_run.stdout_data
    assert "Did you mean: test" in pants_run.stdout_data


def test_unknown_global_flags() -> None:
    pants_run = run_pants(["--pants-workdirx", "goals"],)
    pants_run.assert_failure()
    assert "Unknown flag --pants-workdirx on global scope" in pants_run.stdout_data
    assert "Did you mean --pants-workdir" in pants_run.stdout_data


def test_unknown_scoped_flags() -> None:
    pants_run = run_pants(["test", "--forcex"],)
    pants_run.assert_failure()
    assert "Unknown flag --forcex on test scope" in pants_run.stdout_data
    assert "Did you mean --force" in pants_run.stdout_data


def test_global_flag_in_scoped_position() -> None:
    pants_run = run_pants(["test", "--pants-distdir=dist/"],)
    pants_run.assert_failure()
    assert "Unknown flag --pants-distdir on test scope" in pants_run.stdout_data
    assert "Did you mean to use the global --pants-distdir?" in pants_run.stdout_data
