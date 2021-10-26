# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Iterable

from pants.backend.terraform.target_types import TerraformFieldSet, TerraformModuleSourcesField
from pants.core.goals.fmt import FmtResult, LanguageFmtResults, LanguageFmtTargets
from pants.core.goals.style_request import StyleRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionMembership, UnionRule, union


@dataclass(frozen=True)
class TerraformFmtTargets(LanguageFmtTargets):
    required_fields = (TerraformModuleSourcesField,)


@union
class TerraformFmtRequest(StyleRequest):
    field_set_type = TerraformFieldSet


@rule
async def format_terraform_targets(
    terraform_fmt_targets: TerraformFmtTargets, union_membership: UnionMembership
) -> LanguageFmtResults:
    original_sources = await Get(
        SourceFiles,
        SourceFilesRequest(
            target[TerraformModuleSourcesField] for target in terraform_fmt_targets.targets
        ),
    )
    prior_formatter_result = original_sources.snapshot

    results = []
    fmt_request_types: Iterable[type[StyleRequest]] = union_membership[TerraformFmtRequest]
    for fmt_request_type in fmt_request_types:
        request = fmt_request_type(
            (
                fmt_request_type.field_set_type.create(target)
                for target in terraform_fmt_targets.targets
                if fmt_request_type.field_set_type.is_applicable(target)
            ),
            prior_formatter_result=prior_formatter_result,
        )
        if not request.field_sets:
            continue
        result = await Get(FmtResult, TerraformFmtRequest, request)
        results.append(result)
        if result.did_change:
            prior_formatter_result = await Get(Snapshot, Digest, result.output)
    return LanguageFmtResults(
        tuple(results),
        input=original_sources.snapshot.digest,
        output=prior_formatter_result.digest,
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(LanguageFmtTargets, TerraformFmtTargets),
    ]
