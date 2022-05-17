# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json

from pants.backend.experimental.scala.register import rules as scala_rules
from pants.backend.scala.dependency_inference.scala_parser import ScalaSourceDependencyAnalysis
from pants.backend.scala.target_types import ScalaFieldSet
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import Targets
from pants.jvm.goals import debug_goals


class DumpScalaSourceAnalysisSubsystem(GoalSubsystem):
    name = "scala-dump-source-analysis"
    help = "Dump source analysis for scala_source targets."


class DumpScalaSourceAnalysis(Goal):
    subsystem_cls = DumpScalaSourceAnalysisSubsystem


@goal_rule
async def dump_scala_source_analysis(targets: Targets, console: Console) -> DumpScalaSourceAnalysis:
    scala_source_field_sets = [
        ScalaFieldSet.create(tgt) for tgt in targets if ScalaFieldSet.is_applicable(tgt)
    ]
    scala_source_analysis = await MultiGet(
        Get(ScalaSourceDependencyAnalysis, SourceFilesRequest([fs.sources]))
        for fs in scala_source_field_sets
    )
    scala_source_analysis_json = [
        {"address": str(fs.address), **analysis.to_debug_json_dict()}
        for (fs, analysis) in zip(scala_source_field_sets, scala_source_analysis)
    ]
    console.print_stdout(json.dumps(scala_source_analysis_json))
    return DumpScalaSourceAnalysis(exit_code=0)


def rules():
    return [
        *collect_rules(),
        *scala_rules(),
        *debug_goals.rules(),
    ]
