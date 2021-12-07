# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import Iterable

from pants.backend.java.target_types import JavaSourceField
from pants.core.goals.fmt import FmtResult, LanguageFmtResults, LanguageFmtTargets
from pants.core.goals.style_request import StyleRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionMembership, UnionRule, union


@dataclass(frozen=True)
class JavaFmtTargets(LanguageFmtTargets):
    required_fields = (JavaSourceField,)


@union
class JavaFmtRequest(StyleRequest):
    pass


@rule
async def format_java_target(
    java_fmt_targets: JavaFmtTargets, union_membership: UnionMembership
) -> LanguageFmtResults:
    original_sources = await Get(
        SourceFiles,
        SourceFilesRequest(target[JavaSourceField] for target in java_fmt_targets.targets),
    )
    prior_formatter_result = original_sources.snapshot

    results = []
    fmt_request_types: Iterable[type[StyleRequest]] = union_membership[JavaFmtRequest]
    for fmt_request_type in fmt_request_types:
        request = fmt_request_type(
            (
                fmt_request_type.field_set_type.create(target)
                for target in java_fmt_targets.targets
                if fmt_request_type.field_set_type.is_applicable(target)
            ),
            prior_formatter_result=prior_formatter_result,
        )
        if not request.field_sets:
            continue
        result = await Get(FmtResult, JavaFmtRequest, request)
        results.append(result)
        if result.did_change:
            prior_formatter_result = await Get(Snapshot, Digest, result.output)
    return LanguageFmtResults(
        tuple(results),
        input=original_sources.snapshot.digest,
        output=prior_formatter_result.digest,
    )


def rules():
    return [*collect_rules(), UnionRule(LanguageFmtTargets, JavaFmtTargets)]
