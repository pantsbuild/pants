# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.base.exiter import ExitCode
from pants.base.specs import Specs
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.explorer import ExplorerServer, ExplorerServerRequest, RequestState
from pants.engine.target import RegisteredTargetTypes
from pants.engine.unions import UnionMembership
from pants.goal.builtin_goal import BuiltinGoal
from pants.help.help_info_extracter import HelpInfoExtracter
from pants.init.engine_initializer import GraphSession
from pants.option.option_types import IntOption, StrOption
from pants.option.options import Options
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class ExplorerBuiltinGoal(BuiltinGoal):
    name = "experimental-explorer"
    help = "Run the Pants Explorer Web UI server."
    address = StrOption("--address", default="localhost", help="Server address to bind to.")
    port = IntOption("--port", default=8000, help="Server port to bind to.")

    def run(
        self,
        build_config: BuildConfiguration,
        graph_session: GraphSession,
        options: Options,
        specs: Specs,
        union_membership: UnionMembership,
    ) -> ExitCode:
        for server_request_type in union_membership.get(ExplorerServerRequest):
            logger.info(f"Using {server_request_type.__name__} to create the explorer server.")
            break
        else:
            logger.error(
                softwrap(
                    """
                    There is no Explorer backend server implementation registered.

                    Activate a backend/plugin that registers an implementation for the
                    `ExplorerServerRequest` union to fix this issue.
                    """
                )
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
        server_request = server_request_type(
            address=self.address,
            port=self.port,
            request_state=request_state,
        )
        server = request_state.product_request(
            ExplorerServer,
            (server_request,),
            poll=True,
            timeout=90,
        )
        return server.run()
