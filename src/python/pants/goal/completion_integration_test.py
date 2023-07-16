from pants.testutil.pants_integration_test import PantsResult, run_pants
from pants.goal.completion import CompletionBuiltinGoal
from pants.option.option_value_container import OptionValueContainer
from pants.option.options_test import create_options
from pants.testutil.option_util import create_goal_subsystem, create_options_bootstrapper
from pants.testutil.rule_runner import RuleRunner, mock_console, run_rule_with_mocks

def test_get_previous_goal():
    helper = CompletionBuiltinGoal(OptionValueContainer({}))
    assert helper._get_previous_goal([""]) == None
    assert helper._get_previous_goal(["--keep_sandboxes=always"]) == None
    assert helper._get_previous_goal(["--keep_sandboxes=always", "fmt"]) == "fmt"
    assert helper._get_previous_goal(["--keep_sandboxes=always", "fmt", "--only"]) == "fmt"
    assert helper._get_previous_goal(["--keep_sandboxes=always", "fmt", "--only", "lint"]) == "lint"
    assert helper._get_previous_goal(["--keep_sandboxes=always", "fmt", "--only", "lint", "::"]) == "lint"


def run_pants_complete(args: list[str]) -> PantsResult:
    return run_pants(["pants", "complete", "--", *args])

def test_completion_script_generation():
    default_result = run_pants(["pants", "complete"])
    assert default_result.exit_code == 0
    bash_result = run_pants(["pants", "complete", "--shell=bash"])
    assert bash_result.exit_code == 0
    zsh_result = run_pants(["pants", "complete", "--shell=zsh"])
    assert zsh_result.exit_code == 0

def test_completions_with_no_args():
    result = run_pants_complete([])
    assert result.exit_code == 0

def test_completions_with_global_options():
    result = run_pants_complete(["-"])
    assert result.exit_code == 0
    assert result.stdout == ""

def test_completions_with_all_goals():
    result = run_pants([""])
    assert result.exit_code == 0

def test_completions_with_all_goals_excluding_previous_goals():
    result = run_pants(["check", ""])
    assert result.exit_code == 0

def test_completions_with_goal_options():
    result = run_pants(["check", "-"])
    assert result.exit_code == 0

def test_completions_with_options_on_invalid_goal():
    result = run_pants(["invalid-goal", "-"])   
    assert result.exit_code == 0
    assert result.stdout == ""
