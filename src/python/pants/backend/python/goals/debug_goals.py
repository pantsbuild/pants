# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
from dataclasses import dataclass
from typing import Any, Iterable, List

from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsedPythonDependencies,
)
from pants.backend.python.dependency_inference.rules import (
    ExecParseDepsRequest,
    ExecParseDepsResponse,
    PythonImportDependenciesInferenceFieldSet,
    ResolvedParsedPythonDependencies,
    ResolvedParsedPythonDependenciesRequest,
)
from pants.backend.python.goals.run_python_source import PythonSourceFieldSet
from pants.backend.python.subsystems.setup import PythonSetup
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.target import Targets


class DumpPythonSourceAnalysisSubsystem(GoalSubsystem):
    name = "python-dump-source-analysis"
    help = "Dump source analysis for python_source targets."


class DumpPythonSourceAnalysis(Goal):
    subsystem_cls = DumpPythonSourceAnalysisSubsystem


def flatten(list_of_lists: Iterable[Iterable[Any]]) -> List[Any]:
    return [item for sublist in list_of_lists for item in sublist]


@dataclass(frozen=True)
class PythonSourceAnalysis:
    fs: PythonImportDependenciesInferenceFieldSet
    identified: ParsedPythonDependencies
    resolved: ResolvedParsedPythonDependencies

    def serialisable(self):
        return {
            "address": str(self.fs.address),
            "identified": {
                "imports": self.identified.imports.serialisable(),
                "assets": self.identified.assets.serialisable(),
            },
            "resolved": self.resolved.serialisable(),
        }


@rule
async def dump_python_source_analysis_single(
    fs: PythonImportDependenciesInferenceFieldSet,
    python_setup: PythonSetup,
) -> PythonSourceAnalysis:
    parsed_dependencies = (
        await Get(
            ExecParseDepsResponse,
            ExecParseDepsRequest,
            ExecParseDepsRequest(fs),
        )
    ).value

    resolve = fs.resolve.normalized_value(python_setup)

    resolved_dependencies = await Get(
        ResolvedParsedPythonDependencies,
        ResolvedParsedPythonDependenciesRequest(fs, parsed_dependencies, resolve),
    )

    return PythonSourceAnalysis(fs, parsed_dependencies, resolved_dependencies)


@goal_rule
async def dump_python_source_analysis(
    targets: Targets,
    console: Console,
) -> DumpPythonSourceAnalysis:
    source_field_sets = [
        PythonImportDependenciesInferenceFieldSet.create(tgt)
        for tgt in targets
        if PythonSourceFieldSet.is_applicable(tgt)
    ]

    source_analysis = await MultiGet(
        Get(
            PythonSourceAnalysis,
            PythonImportDependenciesInferenceFieldSet,
            fs,
        )
        for fs in source_field_sets
    )
    marshalled = [
        analysis.serialisable() for (fs, analysis) in zip(source_field_sets, source_analysis)
    ]
    console.print_stdout(json.dumps(marshalled))
    return DumpPythonSourceAnalysis(exit_code=0)


def rules():
    return [
        *collect_rules(),
    ]
