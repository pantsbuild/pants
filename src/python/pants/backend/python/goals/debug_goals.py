# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional, Union

from pants.backend.project_info.peek import _PeekJsonEncoder
from pants.backend.python.dependency_inference.module_mapper import ResolveName
from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsedPythonAssetPaths,
    ParsedPythonDependencies,
    ParsedPythonImportInfo,
)
from pants.backend.python.dependency_inference.rules import (
    ExecParseDepsResponse,
    ImportResolveResult,
    PythonImportDependenciesInferenceFieldSet,
    ResolvedParsedPythonDependencies,
    ResolvedParsedPythonDependenciesRequest,
    UnownedImportsPossibleOwners,
    UnownedImportsPossibleOwnersRequest,
    _collect_imports_info,
)
from pants.backend.python.goals.run_python_source import PythonSourceFieldSet
from pants.backend.python.subsystems.setup import PythonSetup
from pants.build_graph.address import Address
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


@dataclass(frozen=True)
class PythonSourceAnalysis:
    """Information on the inferred imports for a Python file, including all raw intermediate
    results."""

    fs: PythonImportDependenciesInferenceFieldSet
    identified: ParsedPythonDependencies
    resolved: ResolvedParsedPythonDependencies
    possible_owners: UnownedImportsPossibleOwners


@rule
async def dump_python_source_analysis_single(
    fs: PythonImportDependenciesInferenceFieldSet,
    python_setup: PythonSetup,
) -> PythonSourceAnalysis:
    """Infer the dependencies for a single python fieldset, keeping all the intermediate results."""

    parsed_dependencies = (
        await Get(
            ExecParseDepsResponse,
            PythonImportDependenciesInferenceFieldSet,
            fs,
        )
    ).value

    resolve = fs.resolve.normalized_value(python_setup)

    resolved_dependencies = await Get(
        ResolvedParsedPythonDependencies,
        ResolvedParsedPythonDependenciesRequest(fs, parsed_dependencies, resolve),
    )

    import_deps, unowned_imports = _collect_imports_info(resolved_dependencies.resolve_results)

    imports_to_other_owners = await Get(
        UnownedImportsPossibleOwners,
        UnownedImportsPossibleOwnersRequest(unowned_imports, resolve),
    )

    return PythonSourceAnalysis(
        fs, parsed_dependencies, resolved_dependencies, imports_to_other_owners
    )


@dataclass(frozen=True)
class ImportAnalysis:
    """Information on the inferred imports for a Python file."""

    name: str
    reference: Union[ParsedPythonImportInfo, ParsedPythonAssetPaths]
    resolved: ImportResolveResult
    possible_resolve: Optional[list[tuple[Address, ResolveName]]]


def collect_analysis(raw: PythonSourceAnalysis) -> List[ImportAnalysis]:
    """Collect raw analysis and present it in a helpful per-import format."""
    out = []

    resolved_results = raw.resolved.resolve_results

    for name, info in raw.identified.imports.items():
        possible_resolve = raw.possible_owners.value.get(name)

        out.append(
            ImportAnalysis(
                name=name,
                reference=info,
                resolved=resolved_results[name],
                possible_resolve=possible_resolve,
            )
        )

    return out


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

    collected = {str(a.fs.address): collect_analysis(a) for a in source_analysis}

    # console.print_stdout(json.dumps(source_analysis, cls=_PeekJsonEncoder))
    console.print_stdout(json.dumps(collected, cls=_PeekJsonEncoder))
    return DumpPythonSourceAnalysis(exit_code=0)


def rules():
    return [
        *collect_rules(),
    ]
