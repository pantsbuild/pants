# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.base.exiter import ExitCode
from pants.base.specs import Specs
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.unions import UnionMembership
from pants.goal.builtin_goal import BuiltinGoal
from pants.init.engine_initializer import GraphSession
from pants.option.options import Options

logger = logging.getLogger(__name__)


class MigrateCallByNameBuiltinGoal(BuiltinGoal):
    name = "migrate-call-by-name"
    help = "Migrate from `Get` syntax to call-by-name syntax. See #19730."

    def run(
        self,
        build_config: BuildConfiguration,
        graph_session: GraphSession,
        options: Options,
        specs: Specs,
        union_membership: UnionMembership,
    ) -> ExitCode:
        # Emit all `@rules` which use non-union Gets.
        for rule, dependencies in graph_session.scheduler_session.rule_graph_rule_gets().items():
            print(f"{rule}")
            for output_type, input_types, rule_dep in dependencies:
                print(f"  Get({output_type}, {input_types}) -> {rule_dep}")

        return 0
