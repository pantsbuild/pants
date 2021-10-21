# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json

from pants.backend.java.dependency_inference.package_mapper import FirstPartyJavaPackageMapping
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import collect_rules, goal_rule


class DumpDepInferenceDataSubsystem(GoalSubsystem):
    name = "x-java-dump-dep-inf-data"
    help = "Dump dependency inference data for Java dep inference."


class DumpDepInferenceData(Goal):
    subsystem_cls = DumpDepInferenceDataSubsystem


@goal_rule
async def dump_dep_inference_data(
    console: Console, first_party_dep_map: FirstPartyJavaPackageMapping
) -> DumpDepInferenceData:
    console.write_stdout(
        json.dumps(first_party_dep_map.package_rooted_dependency_map.to_json_dict())
    )
    return DumpDepInferenceData(exit_code=0)


def rules():
    return collect_rules()
