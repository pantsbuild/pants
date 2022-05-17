# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.codegen.thrift.subsystem import ThriftSubsystem
from pants.backend.codegen.thrift.target_types import ThriftSourcesGeneratorTarget
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
    group_by_dir,
)
from pants.engine.fs import PathGlobs, Paths
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeThriftTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate Thrift targets to create")
async def find_putative_thrift_targets(
    req: PutativeThriftTargetsRequest,
    all_owned_sources: AllOwnedSources,
    thrift_subsystem: ThriftSubsystem,
) -> PutativeTargets:
    if not thrift_subsystem.tailor:
        return PutativeTargets()

    all_thrift_files = await Get(Paths, PathGlobs, req.search_paths.path_globs("*.thrift"))
    unowned_thrift_files = set(all_thrift_files.files) - set(all_owned_sources)
    pts = [
        PutativeTarget.for_target_type(
            ThriftSourcesGeneratorTarget,
            path=dirname,
            name=None,
            triggering_sources=sorted(filenames),
        )
        for dirname, filenames in group_by_dir(unowned_thrift_files).items()
    ]
    return PutativeTargets(pts)


def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeThriftTargetsRequest),
    ]
