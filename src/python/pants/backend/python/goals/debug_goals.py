# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json

from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsedPythonDependencies,
    ParsePythonDependenciesRequest,
)
from pants.backend.python.dependency_inference.rules import (
    PythonImportDependenciesInferenceFieldSet,
    PythonInferSubsystem,
    _exec_parse_deps,
)
from pants.backend.python.goals.run_python_source import PythonSourceFieldSet
from pants.backend.python.subsystems.setup import PythonSetup
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import Targets


class DumpPythonSourceAnalysisSubsystem(GoalSubsystem):
    name = "python-dump-source-analysis"
    help = "Dump source analysis for python_source targets."


class DumpPythonSourceAnalysis(Goal):
    subsystem_cls = DumpPythonSourceAnalysisSubsystem


@goal_rule
async def dump_python_source_analysis(
    targets: Targets,
    console: Console,
    python_infer_subsystem: PythonInferSubsystem,
    python_setup: PythonSetup,
) -> DumpPythonSourceAnalysis:
    source_field_sets = [
        PythonImportDependenciesInferenceFieldSet.create(tgt)
        for tgt in targets
        if PythonSourceFieldSet.is_applicable(tgt)
    ]

    source_analysis = await MultiGet(
        Get(
            ParsedPythonDependencies,
            ParsePythonDependenciesRequest,
            _exec_parse_deps(fs, python_infer_subsystem, python_setup),
        )
        for fs in source_field_sets
    )
    marshalled = [
        {"address": str(fs.address), "analysis": analysis.serialisable()}
        for (fs, analysis) in zip(source_field_sets, source_analysis)
    ]
    console.print_stdout(json.dumps(marshalled))
    return DumpPythonSourceAnalysis(exit_code=0)


def rules():
    return [
        *collect_rules(),
    ]
