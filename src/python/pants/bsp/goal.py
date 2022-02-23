# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
import os
import sys

from pants.base.exiter import ExitCode
from pants.base.specs import Specs
from pants.bsp.protocol import BSPConnection
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.unions import UnionMembership
from pants.goal.builtin_goal import BuiltinGoal
from pants.init.engine_initializer import GraphSession
from pants.option.options import Options

_logger = logging.getLogger(__name__)


class BSPGoal(BuiltinGoal):
    name = "experimental-bsp"
    help = "Run server for Build Server Protocol (https://build-server-protocol.github.io/)."

    def run(
        self,
        *,
        build_config: BuildConfiguration,
        graph_session: GraphSession,
        options: Options,
        specs: Specs,
        union_membership: UnionMembership
    ) -> ExitCode:
        scheduler_session = graph_session.scheduler_session.scheduler.new_session(
            build_id="bsp", dynamic_ui=False
        )

        saved_stdout = sys.stdout
        saved_stdin = sys.stdin
        try:
            sys.stdout = os.fdopen(sys.stdout.fileno(), "wb", buffering=0)  # type: ignore[assignment]
            sys.stdin = os.fdopen(sys.stdin.fileno(), "rb", buffering=0)  # type: ignore[assignment]
            conn = BSPConnection(
                scheduler_session,
                sys.stdin,  # type: ignore[arg-type]
                sys.stdout,  # type: ignore[arg-type]
            )
            conn.run()
        finally:
            sys.stdout = saved_stdout
            sys.stdin = saved_stdin

        return ExitCode(0)
