# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Union

from pants.backend.project_info.peek import _PeekJsonEncoder
from pants.backend.python.dependency_inference.module_mapper import ResolveName
from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsedPythonDependencies,
    ParsedPythonImportInfo,
)
from pants.backend.python.dependency_inference.rules import (
    ImportResolveResult,
    PythonImportDependenciesInferenceFieldSet,
    ResolvedParsedPythonDependencies,
    ResolvedParsedPythonDependenciesRequest,
    UnownedImportsPossibleOwners,
    UnownedImportsPossibleOwnersRequest,
    _collect_imports_info,
    _exec_parse_deps,
    _find_other_owners_for_unowned_imports,
    import_rules,
)
from pants.backend.python.goals.run_python_source import PythonSourceFieldSet
from pants.backend.python.subsystems.setup import PythonSetup
from pants.build_graph.address import Address
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.target import Targets
from pants.option.option_types import EnumOption
from pants.util.strutil import softwrap


class AnalysisFlavor(Enum):
    raw_dependency_inference = "raw_dependency_inference"
    dependency_inference = "dependency_inference"


class DumpPythonSourceAnalysisSubsystem(GoalSubsystem):
    name = "python-dump-source-analysis"
    help = "Dump source analysis for python_source targets."

    flavor = EnumOption(
        "--analysis-flavor",
        default=AnalysisFlavor.dependency_inference,
        help=softwrap(
            f"""\
            The type of information that should be returned.\n
            * `{AnalysisFlavor.dependency_inference.value}`: The results of dependency inference, for every detected import in every file.\n
            * `{AnalysisFlavor.raw_dependency_inference.value}`: The raw intermediate results of the dependency inference process,
            at every stage they're available.
            Potentially useful for debugging the dependency inference process.\n
            """
        ),
    )


class DumpPythonSourceAnalysis(Goal):
    subsystem_cls = DumpPythonSourceAnalysisSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY  # TODO(#17129) — Migrate this.


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

    parsed_dependencies = await _exec_parse_deps(fs, python_setup)

    resolve = fs.resolve.normalized_value(python_setup)

    resolved_dependencies = await Get(
        ResolvedParsedPythonDependencies,
        ResolvedParsedPythonDependenciesRequest(fs, parsed_dependencies, resolve),
    )

    import_deps, unowned_imports = _collect_imports_info(resolved_dependencies.resolve_results)

    imports_to_other_owners = await _find_other_owners_for_unowned_imports(
        UnownedImportsPossibleOwnersRequest(unowned_imports, resolve),
    )

    return PythonSourceAnalysis(
        fs, parsed_dependencies, resolved_dependencies, imports_to_other_owners
    )


@dataclass(frozen=True)
class ImportAnalysis:
    """Information on the inferred imports for a Python file."""

    name: str
    reference: Union[ParsedPythonImportInfo, str]
    resolved: ImportResolveResult
    possible_resolve: Optional[list[tuple[Address, ResolveName]]]


@dataclass(frozen=True)
class CollectedImportAnalysis:
    """Collected information on all Python files."""

    imports: list[ImportAnalysis]
    assets: list[ImportAnalysis]


def collect_analysis(raw: PythonSourceAnalysis) -> CollectedImportAnalysis:
    """Collect raw analysis and present it in a helpful per-import format."""
    imports = []

    resolved_results = raw.resolved.resolve_results

    for name, info in raw.identified.imports.items():
        possible_resolve = raw.possible_owners.value.get(name)

        imports.append(
            ImportAnalysis(
                name=name,
                reference=info,
                resolved=resolved_results[name],
                possible_resolve=possible_resolve,
            )
        )

    assets = []
    resolved_assets = raw.resolved.assets

    for name in raw.identified.assets:
        possible_resolve = raw.possible_owners.value.get(name)

        assets.append(
            ImportAnalysis(
                name=name,
                reference=name,  # currently assets don't keep track of their line numbers
                resolved=resolved_assets[name],
                possible_resolve=possible_resolve,
            )
        )

    return CollectedImportAnalysis(imports, assets)


@goal_rule
async def dump_python_source_analysis(
    request: DumpPythonSourceAnalysisSubsystem,
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

    output: Any
    if request.flavor == AnalysisFlavor.raw_dependency_inference:
        output = source_analysis
    else:
        output = {str(a.fs.address): collect_analysis(a) for a in source_analysis}

    console.print_stdout(json.dumps(output, cls=_PeekJsonEncoder))
    return DumpPythonSourceAnalysis(exit_code=0)


def rules():
    return [
        *import_rules(),
        *collect_rules(),
    ]
