# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Iterable, List, Type

from pants.backend.python.rules.targets import PythonSources
from pants.engine.fs import Digest, Snapshot
from pants.engine.objects import union
from pants.engine.rules import UnionMembership, UnionRule, rule
from pants.engine.selectors import Get
from pants.rules.core.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.rules.core.fmt import (
    FmtConfigurations,
    FmtResult,
    LanguageFmtResults,
    LanguageFmtTargets,
)


@dataclass(frozen=True)
class PythonFmtTargets(LanguageFmtTargets):
    required_fields = (PythonSources,)


@union
class PythonFmtConfigurations:
    pass


@rule
async def format_python_target(
    python_fmt_targets: PythonFmtTargets, union_membership: UnionMembership
) -> LanguageFmtResults:
    targets_with_origins = python_fmt_targets.targets_with_origins
    original_sources = await Get[SourceFiles](
        AllSourceFilesRequest(
            target_with_origin.target[PythonSources]
            for target_with_origin in python_fmt_targets.targets_with_origins
        )
    )
    prior_formatter_result = original_sources.snapshot

    results: List[FmtResult] = []
    config_collection_types: Iterable[Type[FmtConfigurations]] = union_membership.union_rules[
        PythonFmtConfigurations
    ]
    for config_collection_type in config_collection_types:
        result = await Get[FmtResult](
            PythonFmtConfigurations,
            config_collection_type(
                (
                    config_collection_type.config_type.create(target_with_origin)
                    for target_with_origin in targets_with_origins
                ),
                prior_formatter_result=prior_formatter_result,
            ),
        )
        if result != FmtResult.noop():
            results.append(result)
            prior_formatter_result = await Get[Snapshot](Digest, result.digest)
    return LanguageFmtResults(
        tuple(results), combined_digest=prior_formatter_result.directory_digest
    )


def rules():
    return [format_python_target, UnionRule(LanguageFmtTargets, PythonFmtTargets)]
