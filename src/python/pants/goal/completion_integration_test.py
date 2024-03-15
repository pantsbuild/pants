# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.goal.completion import CompletionBuiltinGoal
from pants.option.option_value_container import OptionValueContainer
from pants.testutil.pants_integration_test import PantsResult, run_pants


def test_get_previous_goal():
    helper = CompletionBuiltinGoal(OptionValueContainer({}))
    assert helper._get_previous_goal([""]) is None
    assert helper._get_previous_goal(["--keep_sandboxes=always"]) is None
    assert helper._get_previous_goal(["--keep_sandboxes=always", "fmt"]) == "fmt"
    assert helper._get_previous_goal(["--keep_sandboxes=always", "fmt", "--only"]) == "fmt"
    assert helper._get_previous_goal(["--keep_sandboxes=always", "fmt", "--only", "lint"]) == "lint"
    assert (
        helper._get_previous_goal(["--keep_sandboxes=always", "fmt", "--only", "lint", "::"])
        == "lint"
    )


def run_pants_complete(args: list[str]) -> PantsResult:
    """While there may be a way to test tab-completion directly in pytest, that feels too clever.

    We can equivalently test the command that the tab-completion will call.

    Note: The "pants" after "--" is intentional, as that's how the completion script would call it.
    """
    return run_pants(["pants", "complete", "--", "pants", *args])


def test_completion_script_generation():
    default_result = run_pants(["complete"])
    default_result.assert_success()

    bash_result = run_pants(["complete", "--shell=bash"])
    print(bash_result.stdout)
    bash_result.assert_success()
    assert "COMPREPLY" in bash_result.stdout

    zsh_result = run_pants(["complete", "--shell=zsh"])
    zsh_result.assert_success()
    assert "compdef" in zsh_result.stdout

    other_result = run_pants(["complete", "--shell=gibberish"])
    other_result.assert_failure()


def test_completions_with_global_options():
    result = run_pants_complete(["-"])
    result.assert_success()
    lines = result.stdout.splitlines()
    assert all(line.startswith("--") for line in lines)
    assert all(o in lines for o in ("--backend_packages", "--colors", "--loop"))  # Spot check


def test_completions_with_all_goals():
    result = run_pants_complete([""])
    result.assert_success()
    lines = result.stdout.splitlines()
    assert all(not line.startswith("-") for line in lines)
    assert all(o in lines for o in ("check", "help", "version"))  # Spot check


def test_completions_with_all_goals_excluding_previous_goals():
    result = run_pants_complete(["check", ""])
    result.assert_success()
    lines = result.stdout.splitlines()
    assert "check" not in lines


def test_completions_with_goal_options():
    result = run_pants_complete(["fmt", "-"])
    result.assert_success()
    lines = result.stdout.splitlines()
    assert lines == ["--batch_size", "--only"]


def test_completions_with_options_on_invalid_goal():
    result = run_pants_complete(["invalid-goal", "-"])
    result.assert_success()
    assert result.stdout == ""
