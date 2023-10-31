# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import collect_rules, goal_rule
from pants.option.option_types import FileOption


class LifecycleStubsSubsystem(GoalSubsystem):

    name = "lifecycle-stub-goal"
    help = """Configure workflows for lifecycle tests (Pants stopping and starting)."""

    new_interactive_stream_output_file = FileOption(
        default=None,
        help="Redirect interactive output into a separate file.",
    )


class LifecycleStubsGoal(Goal):
    subsystem_cls = LifecycleStubsSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


@goal_rule
async def run_lifecycle_stubs(opts: LifecycleStubsSubsystem) -> LifecycleStubsGoal:
    output_file = opts.new_interactive_stream_output_file
    if output_file:
        file_stream = open(output_file, "wb")
    raise Exception("erroneous!")


def rules():
    return collect_rules()


if os.environ.get("_RAISE_EXCEPTION_ON_IMPORT", False):
    raise Exception("exception during import!")

if os.environ.get("_IMPORT_REQUIREMENT", False):
    import pydash