# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass

from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
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
class PutativeProtobufTargetsRequest:
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate Protobuf targets to create")
async def find_putative_targets(
    _: PutativeProtobufTargetsRequest, all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    all_proto_files = await Get(Paths, PathGlobs(["**/*.proto"]))
    unowned_proto_files = set(all_proto_files.files) - set(all_owned_sources)
    pts = [
        PutativeTarget.for_target_type(
            ProtobufLibrary,
            path=dirname,
            name=os.path.basename(dirname),
            triggering_sources=sorted(filenames),
        )
        for dirname, filenames in group_by_dir(unowned_proto_files).items()
    ]
    return PutativeTargets(pts)


def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeProtobufTargetsRequest),
    ]
