# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from unittest.mock import Mock

import pytest

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import goal_rule
from pants.testutil.engine.util import MockConsole, run_rule


@pytest.mark.skip(
  reason="Figure out how to create a GoalSubsystem for tests. We can't call global_instance()"
)
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

  mock_console = MockConsole()
  # TODO: how should we mock `GoalSubsystem`s passed to `run_rule`?
  mock_options = Mock()
  mock_options.output = OutputtingGoalOptions.output
  mock_options.line_oriented = OutputtingGoalOptions.line_oriented
  result: OutputtingGoal = run_rule(output_rule, rule_args=[mock_console, mock_options])
  assert result.exit_code == 0
  assert mock_console.stdout.getvalue() == "output...line oriented"
