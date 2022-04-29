# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping

from pants.backend.python.lint.import_linter.subsystem import (
    ImportLinter,
    ImportLinterConfigFile,
    ImportLinterCustomContracts,
    ImportLinterFieldSet,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.pex import Pex, PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.backend.python.util_rules import python_sources
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.lint import LintResult, LintResults, LintTargetsRequest
from pants.engine.collection import Collection
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTarget, CoarsenedTargets, CoarsenedTargetsRequest, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import pluralize


class ImportLinterRequest(LintTargetsRequest):
    field_set_type = ImportLinterFieldSet
    name = ImportLinter.options_scope


@dataclass(frozen=True)
class ImportLinterPartition:
    root_field_sets: FrozenOrderedSet[ImportLinterFieldSet]
    closure: FrozenOrderedSet[Target]
    resolve_description: str

    def description(self) -> str:
        return self.resolve_description


class ImportLinterPartitions(Collection[ImportLinterPartition]):
    pass


@rule
async def import_linter_determine_partitions(
    request: ImportLinterRequest,
    python_setup: PythonSetup,
) -> ImportLinterPartitions:
    coarsened_targets = await Get(
        CoarsenedTargets,
        CoarsenedTargetsRequest(
            (field_set.address for field_set in request.field_sets), expanded_targets=True
        ),
    )
    coarsened_targets_by_address = coarsened_targets.by_address()

    resolve_to_coarsened_targets: Mapping[
        str, tuple[OrderedSet[ImportLinterFieldSet], OrderedSet[CoarsenedTarget]]
    ] = defaultdict(lambda: (OrderedSet(), OrderedSet()))
    for root in request.field_sets:
        ct = coarsened_targets_by_address[root.address]
        resolve = ct.representative[PythonResolveField].normalized_value(python_setup)
        roots, root_cts = resolve_to_coarsened_targets[resolve]
        roots.add(root)
        root_cts.add(ct)

    return ImportLinterPartitions(
        ImportLinterPartition(
            FrozenOrderedSet(roots), FrozenOrderedSet(CoarsenedTargets(root_cts).closure()), resolve
        )
        for resolve, (roots, root_cts) in sorted(resolve_to_coarsened_targets.items())
    )


@rule
async def import_linter_lint_partition(
    partition: ImportLinterPartition,
    config_file: ImportLinterConfigFile,
    custom_contracts: ImportLinterCustomContracts,
    import_linter: ImportLinter,
) -> LintResult:
    closure_sources_get = Get(PythonSourceFiles, PythonSourceFilesRequest(partition.closure))

    requirements_pex_get = Get(
        Pex,
        RequirementsPexRequest(
            (fs.address for fs in partition.root_field_sets),
            hardcoded_interpreter_constraints=import_linter.interpreter_constraints,
        ),
    )
    import_linter_pex_get = Get(
        VenvPex,
        PexRequest,
        import_linter.to_pex_request(extra_requirements=custom_contracts.requirement_strings),
    )

    (closure_sources, requirements_pex, import_linter_pex,) = await MultiGet(
        closure_sources_get,
        requirements_pex_get,
        import_linter_pex_get,
    )

    merged_input_files = await Get(
        Digest,
        MergeDigests(
            [
                custom_contracts.sources_digest,
                closure_sources.source_files.snapshot.digest,
                requirements_pex.digest,
                config_file.digest,
            ]
        ),
    )

    all_used_source_roots = sorted(
        set(itertools.chain(custom_contracts.source_roots, closure_sources.source_roots))
    )
    env = {"PEX_EXTRA_SYS_PATH": ":".join(all_used_source_roots)}
    argv = []
    if import_linter.config:
        argv.extend(["--config", import_linter.config])

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            import_linter_pex,
            argv=argv,
            input_digest=merged_input_files,
            extra_env=env,
            description=f"Run Import Linter on {pluralize(len(partition.root_field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return LintResult.from_fallible_process_result(
        result, partition_description=partition.description()
    )


@rule(desc="Lint with Import Linter", level=LogLevel.DEBUG)
async def import_linter_lint(
    request: ImportLinterRequest,
    import_linter: ImportLinter,
) -> LintResults:
    if import_linter.skip:
        return LintResults([], linter_name=request.name)

    partitions = await Get(ImportLinterPartitions, ImportLinterRequest, request)
    partitioned_results = await MultiGet(
        Get(LintResult, ImportLinterPartition, partition) for partition in partitions
    )
    return LintResults(partitioned_results, linter_name=request.name)


def rules():
    return [
        *collect_rules(),
        *pex.rules(),
        *pex_from_targets.rules(),
        *python_sources.rules(),
        UnionRule(LintTargetsRequest, ImportLinterRequest),
    ]
