# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.base.deprecated import warn_or_error
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import collect_rules, goal_rule

logger = logging.getLogger(__name__)


class GenerateUserLockfileSubsystem(GoalSubsystem):
    name = "generate-user-lockfile"
    help = (
        "Deprecated: use the option `[python].experimental_resolves` and the "
        "`generate-lockfiles` goal instead"
    )


class GenerateUserLockfileGoal(Goal):
    subsystem_cls = GenerateUserLockfileSubsystem


@goal_rule
async def generate_user_lockfile_goal() -> GenerateUserLockfileGoal:
    warn_or_error(
        "2.11.0.dev0",
        "the `generate-user-lockfile` goal",
        (
            "Instead, configure the option `[python].experimental_resolves`, then use the "
            "`generate-lockfiles` goal. Read the deprecation message on "
            "`[python].experimental_lockfile` for more information."
        ),
    )
    return GenerateUserLockfileGoal(exit_code=1)


def rules():
    return collect_rules()
