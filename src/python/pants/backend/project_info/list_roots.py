# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import goal_rule
from pants.source.source_root import AllSourceRoots


class RootsOptions(LineOriented, GoalSubsystem):
    """List the repo's registered source roots."""

    name = "roots"


class Roots(Goal):
    subsystem_cls = RootsOptions


@goal_rule
async def list_roots(console: Console, options: RootsOptions, asr: AllSourceRoots) -> Roots:
    with options.line_oriented(console) as print_stdout:
        for src_root in asr:
            print_stdout(src_root.path or ".")
    return Roots(exit_code=0)


def rules():
    return [list_roots]
