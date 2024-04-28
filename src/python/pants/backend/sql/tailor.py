# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from pants.backend.sql.target_types import SqlSourcesGeneratorTarget
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets, PutativeTargetsRequest
from pants.engine.fs import PathGlobs, Paths
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.source.filespec import FilespecMatcher
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeSqlTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate sql targets to create")
async def find_putative_targets(req: PutativeSqlTargetsRequest, all_owned_sources: AllOwnedSources) -> PutativeTargets:
    all_sql_files = await Get(Paths, PathGlobs, req.path_globs("*.sql"))
    unowned_sql_files = set(all_sql_files.files) - set(all_owned_sources)
    targets = PutativeTargets(
        [
            PutativeTarget.for_target_type(
                SqlSourcesGeneratorTarget,
                path=dirname,
                name="sql",
                triggering_sources=sorted(filenames),
            )
            for dirname, filenames in group_by_dir(unowned_sql_files).items()
        ]
    )
    # raise RuntimeError(targets)
    return targets


def rules():
    return [*collect_rules(), UnionRule(PutativeTargetsRequest, PutativeSqlTargetsRequest)]
