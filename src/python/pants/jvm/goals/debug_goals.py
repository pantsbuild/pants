# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import collect_rules, goal_rule
from pants.jvm.dependency_inference.symbol_mapper import SymbolMapping


class JvmSymbolMapSubsystem(GoalSubsystem):
    name = "jvm-symbol-map"
    help = "Dump the JVM dependency inference symbol mapping."


class JvmSymbolMap(Goal):
    subsystem_cls = JvmSymbolMapSubsystem


@goal_rule
async def jvm_symbol_map(console: Console, symbol_mapping: SymbolMapping) -> JvmSymbolMap:
    console.print_stdout(json.dumps(symbol_mapping.to_json_dict()))
    return JvmSymbolMap(exit_code=0)


def rules():
    return [
        *collect_rules(),
    ]
