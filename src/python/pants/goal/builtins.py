# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.bsp.goal import BSPGoal
from pants.build_graph.build_configuration import BuildConfiguration
from pants.goal import help
from pants.goal.builtin_goal import BuiltinGoal


def register_builtin_goals(build_configuration: BuildConfiguration.Builder) -> None:
    build_configuration.register_subsystems("pants.goal", builtin_goals())


def builtin_goals() -> tuple[type[BuiltinGoal], ...]:
    return (
        help.AllHelpBuiltinGoal,
        help.NoGoalHelpBuiltinGoal,
        help.ThingHelpBuiltinGoal,
        help.ThingHelpAdvancedBuiltinGoal,
        help.UnknownGoalHelpBuiltinGoal,
        help.VersionHelpBuiltinGoal,
        BSPGoal,
    )
