# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.base.deprecated import warn_or_error
from pants.base.exception_sink import ExceptionSink
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import goal_rule
from pants.option.custom_types import file_option


class DeprecationWarningOptions(GoalSubsystem):
    """Make a deprecation warning so that warning filters can be integration tested."""

    name = "deprecation-warning"


class DeprecationWarningGoal(Goal):
    subsystem_cls = DeprecationWarningOptions


@goal_rule
async def show_warning() -> DeprecationWarningGoal:
    warn_or_error(
        removal_version="999.999.9.dev9", deprecated_entity_description="This is a test warning!",
    )
    return DeprecationWarningGoal(0)


class LifecycleStubsOptions(GoalSubsystem):
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
    subsystem_cls = LifecycleStubsOptions


@goal_rule
async def run_lifecycle_stubs(opts: LifecycleStubsOptions) -> LifecycleStubsGoal:
    output_file = opts.values.new_interactive_stream_output_file
    if output_file:
        file_stream = open(output_file, "wb")
        ExceptionSink.reset_interactive_output_stream(file_stream, output_file)
    raise Exception("erroneous!")


def rules():
    return [show_warning, run_lifecycle_stubs]


if os.environ.get("_RAISE_KEYBOARDINTERRUPT_ON_IMPORT", False):
    raise KeyboardInterrupt("ctrl-c during import!")
