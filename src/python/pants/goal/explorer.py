# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.explorer.api import server
from pants.backend.explorer.request_state import RequestState
from pants.base.exiter import ExitCode
from pants.base.specs import Specs
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.target import RegisteredTargetTypes
from pants.engine.unions import UnionMembership
from pants.goal.builtin_goal import BuiltinGoal
from pants.help.help_info_extracter import HelpInfoExtracter
from pants.init.engine_initializer import GraphSession
from pants.option.options import Options


class ExplorerBuiltinGoal(BuiltinGoal):
    name = "explorer"
    help = "Run the Pants Explorer Web UI server."

    def run(
        self,
        build_config: BuildConfiguration,
        graph_session: GraphSession,
        options: Options,
        specs: Specs,
        union_membership: UnionMembership,
    ) -> ExitCode:
        all_help_info = HelpInfoExtracter.get_all_help_info(
            options,
            union_membership,
            graph_session.goal_consumed_subsystem_scopes,
            RegisteredTargetTypes.create(build_config.target_types),
            build_config,
        )
        server.run(
            RequestState(
                all_help_info=all_help_info,
                build_configuration=build_config,
                scheduler_session=graph_session.scheduler_session,
            ),
        )
        return 0
