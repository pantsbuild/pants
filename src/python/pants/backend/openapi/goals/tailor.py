# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Iterable

from pants.backend.openapi.dependency_inference import OpenApiDependencies, ParseOpenApiSources
from pants.backend.openapi.subsystems.openapi import OpenApiSubsystem
from pants.backend.openapi.target_types import (
    OPENAPI_FILE_EXTENSIONS,
    OpenApiDocumentGeneratorTarget,
    OpenApiSourceGeneratorTarget,
)
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
)
from pants.engine.fs import PathGlobs, Paths
from pants.engine.internals.native_engine import Digest
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeOpenApiTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate OpenAPI targets to create")
async def find_putative_targets(
    req: PutativeOpenApiTargetsRequest,
    all_owned_sources: AllOwnedSources,
    openapi_subsystem: OpenApiSubsystem,
) -> PutativeTargets:
    if not openapi_subsystem.tailor_targets:
        return PutativeTargets()

    all_openapi_files = await Get(
        Paths, PathGlobs, req.path_globs(*(f"**/openapi{ext}" for ext in OPENAPI_FILE_EXTENSIONS))
    )
    targets = {*all_openapi_files.files}
    paths = tuple(targets)

    while paths:
        digest = await Get(Digest, PathGlobs(paths))  # noqa: PNT30: this is inherently sequential
        result = await Get(  # noqa: PNT30: this is inherently sequential
            OpenApiDependencies,
            ParseOpenApiSources(
                sources_digest=digest,
                paths=tuple(paths),
            ),
        )

        targets.update(result.dependencies.keys())
        paths = tuple(v for v in itertools.chain(*result.dependencies.values()) if v not in targets)

    unowned_openapi_documents = set(all_openapi_files.files) - set(all_owned_sources)
    unowned_openapi_sources = targets - set(all_owned_sources)
    classified_unowned_openapi_files = {
        OpenApiDocumentGeneratorTarget: unowned_openapi_documents,
        OpenApiSourceGeneratorTarget: unowned_openapi_sources,
    }

    putative_targets = []
    for tgt_type, filepaths in classified_unowned_openapi_files.items():
        for dirname, filenames in group_by_dir(filepaths).items():
            name = "openapi" if tgt_type == OpenApiDocumentGeneratorTarget else None
            putative_targets.append(
                PutativeTarget.for_target_type(
                    tgt_type, path=dirname, name=name, triggering_sources=sorted(filenames)
                )
            )

    return PutativeTargets(putative_targets)


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeOpenApiTargetsRequest),
    )
