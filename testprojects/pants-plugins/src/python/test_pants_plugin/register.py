# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import collect_rules, goal_rule
from pants.option.custom_types import file_option


class LifecycleStubsSubsystem(GoalSubsystem):
    """Configure workflows for lifecycle tests (Pants stopping and starting)."""

    name = "lifecycle-stub-goal"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--new-interactive-stream-output-file",
            type=file_option,
            default=None,
            help="Redirect interactive output into a separate file.",
        )


class LifecycleStubsGoal(Goal):
    subsystem_cls = LifecycleStubsSubsystem


@goal_rule
async def run_lifecycle_stubs(opts: LifecycleStubsSubsystem) -> LifecycleStubsGoal:
    output_file = opts.options.new_interactive_stream_output_file
    if output_file:
        file_stream = open(output_file, "wb")
    raise Exception("erroneous!")


def rules():
    return collect_rules()


if os.environ.get("_RAISE_KEYBOARDINTERRUPT_ON_IMPORT", False):
    raise KeyboardInterrupt("ctrl-c during import!")
