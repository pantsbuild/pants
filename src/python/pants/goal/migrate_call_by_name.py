# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from functools import partial
import json
import importlib.util
import logging
from pathlib import PurePath
from typing import TypedDict

from pants.base.build_environment import get_buildroot
from pants.base.exiter import ExitCode
from pants.base.specs import Specs
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.unions import UnionMembership
from pants.goal.builtin_goal import BuiltinGoal
from pants.init.engine_initializer import GraphSession
from pants.option.options import Options

logger = logging.getLogger(__name__)

class RuleGraphGet(TypedDict):
    filepath: str
    function: str
    module: str
    gets: list[RuleGraphGetDep]

class RuleGraphGetDep(TypedDict):
    input_types: list[RuleType]
    output_type: RuleType
    rule_dep: RuleFunction

class RuleType(TypedDict):
    module: str
    name: str

class RuleFunction(TypedDict):
    function: str
    module: str



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
        build_root = PurePath(get_buildroot())
        items: list[RuleGraphGet] = []

        for rule, deps in graph_session.scheduler_session.rule_graph_rule_gets().items():
            if isinstance(rule, partial):
                continue
        
            assert (spec := importlib.util.find_spec(rule.__module__)) is not None
            assert (spec.origin is not None)
            spec_origin = PurePath(spec.origin)

            item: RuleGraphGet = { 
                "filepath": str(spec_origin.relative_to(build_root)),
                "module": rule.__module__,
                "function": rule.__name__,
                "gets": [] 
            }
            unsorted_deps: list[RuleGraphGetDep] = []

            for output_type, input_types, rule_dep in deps:
                if isinstance(rule_dep, partial):
                    continue

                unsorted_deps.append(
                    {
                        "input_types": sorted([{
                            "module": input_type.__module__,
                            "name": input_type.__name__,
                        } for input_type in input_types], key=lambda x: (x["module"], x["name"])),
                        "output_type": {
                            "module": output_type.__module__,
                            "name": output_type.__name__,
                        },
                        "rule_dep": {
                            "function": rule_dep.__name__,
                            "module": rule_dep.__module__,
                        }
                    }
                )

            # Sort the dependencies by the rule_dep, and then by the input_types.
            sorted_deps = sorted(unsorted_deps, key=lambda x: (x["rule_dep"]["module"], x["rule_dep"]["function"]))
            item["gets"] = sorted_deps
            items.append(item)
        
        sorted_items = sorted(items, key=lambda x: (x["filepath"], x["function"]))
        print(json.dumps(sorted_items, indent=2, sort_keys=True))
        
        return 0
