# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.backend.cc.target_types import CC_FILE_EXTENSIONS, CCSourcesGeneratorTarget
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
)
from pants.engine.fs import PathGlobs, Paths
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeCCTargetsRequest(PutativeTargetsRequest):
    pass


def classify_source_files(paths: Iterable[str]) -> dict[type[Target], set[str]]:
    """Returns a dict of target type -> files that belong to targets of that type."""
    sources_files = set(paths)
    return {CCSourcesGeneratorTarget: sources_files}


@rule(level=LogLevel.DEBUG, desc="Determine candidate CC targets to create")
async def find_putative_targets(
    req: PutativeCCTargetsRequest,
    all_owned_sources: AllOwnedSources,
) -> PutativeTargets:
    all_cc_files = await Get(
        Paths, PathGlobs, req.path_globs(*(f"*{ext}" for ext in CC_FILE_EXTENSIONS))
    )
    unowned_cc_files = set(all_cc_files.files) - set(all_owned_sources)
    classified_unowned_kotlin_files = classify_source_files(unowned_cc_files)

    putative_targets = []
    for tgt_type, paths in classified_unowned_kotlin_files.items():
        for dirname, filenames in group_by_dir(paths).items():
            putative_targets.append(
                PutativeTarget.for_target_type(
                    tgt_type, path=dirname, name=None, triggering_sources=sorted(filenames)
                )
            )

    return PutativeTargets(putative_targets)


def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeCCTargetsRequest),
    ]
