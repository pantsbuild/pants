# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Iterable, List, Type

from pants.backend.python.target_types import PythonSources
from pants.core.goals.fmt import FmtFieldSets, FmtResult, LanguageFmtResults, LanguageFmtTargets
from pants.core.util_rules.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.engine.fs import Digest, Snapshot
from pants.engine.rules import rule
from pants.engine.selectors import Get
from pants.engine.unions import UnionMembership, UnionRule, union


@dataclass(frozen=True)
class PythonFmtTargets(LanguageFmtTargets):
    required_fields = (PythonSources,)


@union
class PythonFmtFieldSets:
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
    field_set_collection_types: Iterable[Type[FmtFieldSets]] = union_membership.union_rules[
        PythonFmtFieldSets
    ]
    for field_set_collection_type in field_set_collection_types:
        result = await Get[FmtResult](
            PythonFmtFieldSets,
            field_set_collection_type(
                (
                    field_set_collection_type.field_set_type.create(target_with_origin)
                    for target_with_origin in targets_with_origins
                ),
                prior_formatter_result=prior_formatter_result,
            ),
        )
        if result != FmtResult.noop():
            results.append(result)
        if result.did_change:
            prior_formatter_result = await Get[Snapshot](Digest, result.output)
    return LanguageFmtResults(
        tuple(results),
        input=original_sources.snapshot.digest,
        output=prior_formatter_result.digest,
    )


def rules():
    return [format_python_target, UnionRule(LanguageFmtTargets, PythonFmtTargets)]
