# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.target_types import PythonSources
from pants.core.goals.fmt import EnrichedFmtResult, LanguageFmtResults, LanguageFmtTargets
from pants.core.goals.style_request import StyleRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, Snapshot
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionMembership, UnionRule, union


@dataclass(frozen=True)
class PythonFmtTargets(LanguageFmtTargets):
    required_fields = (PythonSources,)


@union
class PythonFmtRequest(StyleRequest):
    pass


@rule
async def format_python_target(
    python_fmt_targets: PythonFmtTargets, union_membership: UnionMembership
) -> LanguageFmtResults:
    original_sources = await Get(
        SourceFiles,
        SourceFilesRequest(target[PythonSources] for target in python_fmt_targets.targets),
    )
    prior_formatter_result = original_sources.snapshot

    results = []
    fmt_request_types = union_membership.union_rules[PythonFmtRequest]
    for fmt_request_type in fmt_request_types:
        request = fmt_request_type(
            (
                fmt_request_type.field_set_type.create(target)
                for target in python_fmt_targets.targets
                if fmt_request_type.field_set_type.is_applicable(target)
            ),
            prior_formatter_result=prior_formatter_result,
        )
        if not request.field_sets:
            continue
        result = await Get(EnrichedFmtResult, PythonFmtRequest, request)
        results.append(result)
        if result.did_change:
            prior_formatter_result = await Get(Snapshot, Digest, result.output)
    return LanguageFmtResults(
        tuple(results),
        input=original_sources.snapshot.digest,
        output=prior_formatter_result.digest,
    )


def rules():
    return [*collect_rules(), UnionRule(LanguageFmtTargets, PythonFmtTargets)]
