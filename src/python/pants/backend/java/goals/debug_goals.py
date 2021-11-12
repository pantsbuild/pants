# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json

from pants.backend.experimental.java.register import rules as java_rules
from pants.backend.java.dependency_inference.types import JavaSourceDependencyAnalysis
from pants.backend.java.target_types import JavaFieldSet
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import Targets
from pants.jvm.dependency_inference.symbol_mapper import FirstPartySymbolMapping


class DumpFirstPartyDepMapSubsystem(GoalSubsystem):
    name = "java-dump-first-party-dep-map"
    help = "Dump dependency inference data for Java dep inference."


class DumpFirstPartyDepMap(Goal):
    subsystem_cls = DumpFirstPartyDepMapSubsystem


@goal_rule
async def dump_dep_inference_data(
    console: Console, first_party_dep_map: FirstPartySymbolMapping
) -> DumpFirstPartyDepMap:
    console.write_stdout(json.dumps(first_party_dep_map.symbols.to_json_dict()))
    return DumpFirstPartyDepMap(exit_code=0)


class DumpJavaSourceAnalysisSubsystem(GoalSubsystem):
    name = "java-dump-source-analysis"
    help = "Dump source analysis for java_source[s] targets."


class DumpJavaSourceAnalysis(Goal):
    subsystem_cls = DumpJavaSourceAnalysisSubsystem


@goal_rule
async def dump_java_source_analysis(targets: Targets, console: Console) -> DumpJavaSourceAnalysis:
    java_source_field_sets = [
        JavaFieldSet.create(tgt) for tgt in targets if JavaFieldSet.is_applicable(tgt)
    ]
    java_source_analysis = await MultiGet(
        Get(JavaSourceDependencyAnalysis, SourceFilesRequest([fs.sources]))
        for fs in java_source_field_sets
    )
    java_source_analysis_json = [
        {"address": str(fs.address), **analysis.to_debug_json_dict()}
        for (fs, analysis) in zip(java_source_field_sets, java_source_analysis)
    ]
    console.write_stdout(json.dumps(java_source_analysis_json))
    return DumpJavaSourceAnalysis(exit_code=0)


def rules():
    return [
        *collect_rules(),
        *java_rules(),
    ]
