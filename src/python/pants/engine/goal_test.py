# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import goal_rule
from pants.testutil.engine.util import MockConsole, create_goal_subsystem, run_rule


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

    console = MockConsole()
    result: OutputtingGoal = run_rule(
        output_rule,
        rule_args=[
            console,
            create_goal_subsystem(OutputtingGoalOptions, sep="\\n", output_file=None),
        ],
    )
    assert result.exit_code == 0
    assert console.stdout.getvalue() == "output...line oriented\n"
