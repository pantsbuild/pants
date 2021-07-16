# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import goal_rule
from pants.option.scope import ScopeInfo
from pants.testutil.option_util import create_goal_subsystem, create_options_bootstrapper
from pants.testutil.rule_runner import mock_console, run_rule_with_mocks


def test_line_oriented_goal() -> None:
    class OutputtingGoalOptions(LineOriented, GoalSubsystem):
        name = "dummy"

    class OutputtingGoal(Goal):
        subsystem_cls = OutputtingGoalOptions

    @goal_rule
    def output_rule(console: Console, options: OutputtingGoalOptions) -> OutputtingGoal:
        with options.output(console) as write_stdout:
            write_stdout("output...")
        with options.line_oriented(console) as print_stdout:
            print_stdout("line oriented")
        return OutputtingGoal(0)

    with mock_console(create_options_bootstrapper()) as (console, stdio_reader):
        result: OutputtingGoal = run_rule_with_mocks(
            output_rule,
            rule_args=[
                console,
                create_goal_subsystem(OutputtingGoalOptions, sep="\\n", output_file=None),
            ],
        )
        assert result.exit_code == 0
        assert stdio_reader.get_stdout() == "output...line oriented\n"


def test_goal_scope_flag() -> None:
    class DummyGoal(GoalSubsystem):
        name = "dummy"

    dummy = create_goal_subsystem(DummyGoal)
    assert dummy.get_scope_info().is_goal is True
    assert dummy.known_scope_infos() == {
        ScopeInfo(scope="dummy", optionable_cls=DummyGoal, is_goal=True)
    }
