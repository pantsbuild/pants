# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.explorer.api import server
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import collect_rules, goal_rule


class ExplorerSubsystem(GoalSubsystem):
    name = "explorer"
    help = "Run the Pants Explorer Web UI."


class Explorer(Goal):
    subsystem_cls = ExplorerSubsystem


@goal_rule
async def run_explorer_backend(
    console: Console, explorer: ExplorerSubsystem, build_configuration: BuildConfiguration
) -> Explorer:
    console.stdout.write("Explorer..\n")
    assert console._session is not None
    server.run(
        server.RequestState(
            build_configuration=build_configuration,
            scheduler_session=console._session,
        ),
    )
    console.stdout.write("Done\n")
    return Explorer(0)


def rules():
    return collect_rules()
