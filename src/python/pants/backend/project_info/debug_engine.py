# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.internals.native_engine import debug_hang

logger = logging.getLogger(__name__)


class DebugEnginetSubsystem(LineOriented, GoalSubsystem):
    name = "debug-engine"
    help = "Foo"


class DebugEngine(Goal):
    subsystem_cls = DebugEnginetSubsystem


@goal_rule
async def debug_engine(console: Console) -> DebugEngine:
    debug_hang(console._session.py_scheduler)
    return DebugEngine(exit_code=0)


def rules():
    return collect_rules()
