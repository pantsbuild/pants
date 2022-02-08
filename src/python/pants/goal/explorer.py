# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.backend.explorer.request_state import RequestState
from pants.backend.explorer.setup import ExplorerServer, ExplorerServerRequest
from pants.base.exiter import ExitCode
from pants.base.specs import Specs
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.target import RegisteredTargetTypes
from pants.engine.unions import UnionMembership
from pants.goal.builtin_goal import BuiltinGoal
from pants.help.help_info_extracter import HelpInfoExtracter
from pants.init.engine_initializer import GraphSession
from pants.option.options import Options

logger = logging.getLogger(__name__)
_EXPLORER_BACKEND_PACKAGE = "pants.backend.experimental.explorer"


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
        global_options = options.for_global_scope()
        if _EXPLORER_BACKEND_PACKAGE not in global_options.backend_packages:
            logger.error(f"The backend `{_EXPLORER_BACKEND_PACKAGE}` is not enabled.")
            return 126

        for server_request_type in union_membership.get(ExplorerServerRequest):
            logger.info(f"Using {server_request_type.__name__} to create the explorer server.")
            break
        else:
            logger.error(
                "There is no Explorer backend server implementation registered. TBW how to resolve."
            )
            return 127

        all_help_info = HelpInfoExtracter.get_all_help_info(
            options,
            union_membership,
            graph_session.goal_consumed_subsystem_scopes,
            RegisteredTargetTypes.create(build_config.target_types),
            build_config,
        )
        request_state = RequestState(
            all_help_info=all_help_info,
            build_configuration=build_config,
            scheduler_session=graph_session.scheduler_session,
        )
        server = request_state.product_request(
            ExplorerServer,
            (server_request_type(request_state),),
            poll=True,
            timeout=90,
        )
        return server.run()
