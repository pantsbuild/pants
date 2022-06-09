# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json

from pants.backend.experimental.kotlin.register import rules as kotlin_rules
from pants.backend.kotlin.dependency_inference.kotlin_parser import KotlinSourceDependencyAnalysis
from pants.backend.kotlin.target_types import KotlinFieldSet
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import Targets
from pants.jvm.goals import debug_goals


class DumpKotlinSourceAnalysisSubsystem(GoalSubsystem):
    name = "kotlin-dump-source-analysis"
    help = "Dump source analysis for kotlin_source targets."


class DumpKotlinSourceAnalysis(Goal):
    subsystem_cls = DumpKotlinSourceAnalysisSubsystem


@goal_rule
async def dump_kotlin_source_analysis(
    targets: Targets, console: Console
) -> DumpKotlinSourceAnalysis:
    kotlin_source_field_sets = [
        KotlinFieldSet.create(tgt) for tgt in targets if KotlinFieldSet.is_applicable(tgt)
    ]
    kotlin_source_analysis = await MultiGet(
        Get(KotlinSourceDependencyAnalysis, SourceFilesRequest([fs.sources]))
        for fs in kotlin_source_field_sets
    )
    kotlin_source_analysis_json = [
        {"address": str(fs.address), **analysis.to_debug_json_dict()}
        for (fs, analysis) in zip(kotlin_source_field_sets, kotlin_source_analysis)
    ]
    console.print_stdout(json.dumps(kotlin_source_analysis_json))
    return DumpKotlinSourceAnalysis(exit_code=0)


def rules():
    return [
        *collect_rules(),
        *kotlin_rules(),
        *debug_goals.rules(),
    ]
