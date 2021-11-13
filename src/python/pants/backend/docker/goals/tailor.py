# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass

from pants.backend.docker.target_types import DockerImageSourceField, DockerImageTarget
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
)
from pants.engine.fs import PathGlobs, Paths
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeDockerTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate Docker targets to create")
async def find_putative_targets(
    req: PutativeDockerTargetsRequest, all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    all_dockerfiles = await Get(Paths, PathGlobs, req.search_paths.path_globs("*Dockerfile*"))
    unowned_dockerfiles = set(all_dockerfiles.files) - set(all_owned_sources)
    pts = []
    for dockerfile in sorted(unowned_dockerfiles):
        dirname, filename = os.path.split(dockerfile)
        kwargs = {}
        if filename != DockerImageSourceField.default:
            kwargs["source"] = filename
        pts.append(
            PutativeTarget.for_target_type(
                DockerImageTarget, dirname, "docker", [filename], kwargs=kwargs
            )
        )
    return PutativeTargets(pts)


def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeDockerTargetsRequest),
    ]
