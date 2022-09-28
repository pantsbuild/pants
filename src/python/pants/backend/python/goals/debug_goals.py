# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json

from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsedPythonDependencies,
    ParsePythonDependenciesRequest,
)
from pants.backend.python.dependency_inference.rules import PythonInferSubsystem
from pants.backend.python.goals.run_python_source import PythonSourceFieldSet
from pants.backend.python.subsystems.setup import PythonSetup
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get
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
        PythonSourceFieldSet.create(tgt)
        for tgt in targets
        if PythonSourceFieldSet.is_applicable(tgt)
    ]
    field_set = source_field_sets[0]

    # interpreter_constraints = InterpreterConstraints.create_from_compatibility_fields(
    #     [request.field_set.interpreter_constraints], python_setup
    # )
    interpreter_constraints = None
    source_analysis = await Get(
        ParsedPythonDependencies,
        ParsePythonDependenciesRequest(
            field_set.source,
            interpreter_constraints,
            string_imports=python_infer_subsystem.string_imports,
            string_imports_min_dots=python_infer_subsystem.string_imports_min_dots,
            assets=python_infer_subsystem.assets,
            assets_min_slashes=python_infer_subsystem.assets_min_slashes,
        ),
    )
    serialised = [str(fs) for fs in source_analysis]
    console.print_stdout(json.dumps(serialised))
    return DumpPythonSourceAnalysis(exit_code=0)


def rules():
    return [
        *collect_rules(),
    ]
