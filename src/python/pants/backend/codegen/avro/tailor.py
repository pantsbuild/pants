# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.codegen.avro.target_types import AvroSourcesGeneratorTarget
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
    group_by_dir,
)
from pants.engine.fs import PathGlobs, Paths
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeAvroTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate Protobuf targets to create")
async def find_putative_targets(
    req: PutativeAvroTargetsRequest, all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    all_avsc_files, all_avpr_files, all_avdl_files = await MultiGet(
        Get(Paths, PathGlobs, req.search_paths.path_globs("*.avsc")),
        Get(Paths, PathGlobs, req.search_paths.path_globs("*.avpr")),
        Get(Paths, PathGlobs, req.search_paths.path_globs("*.avdl")),
    )
    unowned_avro_files = {
        *all_avsc_files.files,
        *all_avpr_files.files,
        *all_avdl_files.files,
    } - set(all_owned_sources)
    pts = [
        PutativeTarget.for_target_type(
            AvroSourcesGeneratorTarget,
            path=dirname,
            name=None,
            triggering_sources=sorted(filenames),
        )
        for dirname, filenames in group_by_dir(unowned_avro_files).items()
    ]
    return PutativeTargets(pts)


def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeAvroTargetsRequest),
    ]
