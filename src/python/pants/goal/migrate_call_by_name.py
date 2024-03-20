# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from functools import partial
import json
import logging
from typing import Any

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
        
        # Create a list of items. Each item is an object using the `rule` module+name as the key.
        # The value is a list of objects.
        # Each object has the output_type as a string, the input_types as a list of strings, and the rule_dep as a string.

        items: list[dict[str, list[dict[str, str]]]] = []

        for rule, deps in graph_session.scheduler_session.rule_graph_rule_gets().items():
            if isinstance(rule, partial):
                continue

            key = rule.__module__ + "." + rule.__name__
            item = { "function": key, "gets": [] }

            unsorted_deps: list[dict[str, Any]] = []
            for output_type, input_types, rule_dep in deps:
                if isinstance(rule_dep, partial):
                    continue
                
                unsorted_deps.append(
                    {
                        "input_types": sorted([input_type.__module__ + "." + input_type.__name__ for input_type in input_types]),
                        "output_type": output_type.__module__ + "." + output_type.__name__,
                        "rule_dep": rule_dep.__module__ + "." + rule_dep.__name__,
                    }
                )

            sorted_deps = sorted(unsorted_deps, key=lambda x: x["rule_dep"])
            item["gets"] = sorted_deps
            items.append(item)
        
        sorted_items = sorted(items, key=lambda x: x["function"])
        print(json.dumps(sorted_items, indent=2, sort_keys=True))
        return 0
