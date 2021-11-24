# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass

from pants.backend.go.lint.vet.skip_field import SkipGoVetField
from pants.backend.go.lint.vet.subsystem import GoVetSubsystem
from pants.backend.go.target_types import GoPackageSourcesField
from pants.backend.go.util_rules.go_mod import (
    GoModInfo,
    GoModInfoRequest,
    OwningGoMod,
    OwningGoModRequest,
)
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class GoVetFieldSet(FieldSet):
    required_fields = (GoPackageSourcesField,)

    sources: GoPackageSourcesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipGoVetField).value


class GoVetRequest(LintRequest):
    field_set_type = GoVetFieldSet


@rule(level=LogLevel.DEBUG)
async def run_go_vet(request: GoVetRequest, go_vet_subsystem: GoVetSubsystem) -> LintResults:
    if go_vet_subsystem.skip:
        return LintResults([], linter_name="go vet")

    source_files = await Get(
        SourceFiles,
        SourceFilesRequest(field_set.sources for field_set in request.field_sets),
    )

    owning_go_mods = await MultiGet(
        Get(OwningGoMod, OwningGoModRequest(field_set.address)) for field_set in request.field_sets
    )

    owning_go_mod_addresses = set(x.address for x in owning_go_mods)

    go_mod_infos = await MultiGet(
        Get(GoModInfo, GoModInfoRequest(address)) for address in owning_go_mod_addresses
    )

    input_digest = await Get(
        Digest,
        MergeDigests([source_files.snapshot.digest, *(info.digest for info in set(go_mod_infos))]),
    )

    package_dirs = sorted(set(os.path.dirname(f) for f in source_files.snapshot.files))

    process_result = await Get(
        FallibleProcessResult,
        GoSdkProcess(
            ("vet", *(f"./{p}" for p in package_dirs)),
            input_digest=input_digest,
            description=f"Run `go vet` on {pluralize(len(source_files.snapshot.files), 'file')}.",
        ),
    )

    result = LintResult.from_fallible_process_result(process_result)
    return LintResults([result], linter_name="go vet")


def rules():
    return [
        *collect_rules(),
        UnionRule(LintRequest, GoVetRequest),
    ]
