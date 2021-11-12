# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget
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
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeScalaTargetsRequest(PutativeTargetsRequest):
    pass


def classify_source_files(paths: Iterable[str]) -> dict[type[Target], set[str]]:
    """Returns a dict of target type -> files that belong to targets of that type."""
    # TODO: Until https://github.com/pantsbuild/pants/issues/13332 is fixed, we classify all scala
    # files as `scala_sources`, and none as tests.
    return {ScalaSourcesGeneratorTarget: set(paths)}


@rule(level=LogLevel.DEBUG, desc="Determine candidate Scala targets to create")
async def find_putative_targets(
    req: PutativeScalaTargetsRequest,
    all_owned_sources: AllOwnedSources,
) -> PutativeTargets:
    all_scala_files_globs = req.search_paths.path_globs("*.scala")
    all_scala_files = await Get(Paths, PathGlobs, all_scala_files_globs)
    unowned_scala_files = set(all_scala_files.files) - set(all_owned_sources)
    classified_unowned_scala_files = classify_source_files(unowned_scala_files)

    putative_targets = []
    for tgt_type, paths in classified_unowned_scala_files.items():
        for dirname, filenames in group_by_dir(paths).items():
            name = os.path.basename(dirname)
            putative_targets.append(
                PutativeTarget.for_target_type(
                    tgt_type, dirname, name, sorted(filenames), kwargs={}
                )
            )

    return PutativeTargets(putative_targets)


def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeScalaTargetsRequest),
    ]
