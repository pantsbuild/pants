# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from pants.backend.tools.semgrep.subsystem import SemgrepSubsystem
from pants.backend.tools.semgrep.target_types import SemgrepRuleSourcesGeneratorTarget
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
class PutativeSemgrepTargetsRequest(PutativeTargetsRequest):
    pass


def _group_by_semgrep_dir(paths: Iterable[str]) -> dict[str, set[str]]:
    ret = defaultdict(set)
    for path in paths:
        dirname, filename = os.path.split(path)
        dir2name, dir_basename = os.path.split(dirname)
        if dir_basename == ".semgrep":
            # rules from foo/bar/.semgrep/ should behave like they're in foo/bar, not
            # foo/bar/,semgrep
            ret[dir2name].add(os.path.join(dir_basename, filename))
        else:
            ret[dirname].add(filename)

    return ret


@rule(level=LogLevel.DEBUG, desc="Determine candidate Semgrep targets to create")
async def find_putative_targets(
    req: PutativeSemgrepTargetsRequest,
    all_owned_sources: AllOwnedSources,
    semgrep: SemgrepSubsystem,
) -> PutativeTargets:
    pts = []

    if semgrep.tailor_rule_targets:
        all_files_globs = req.path_globs(
            ".semgrep.yml", ".semgrep.yaml", ".semgrep/*.yml", ".semgrep/*.yaml"
        )
        all_files = await Get(Paths, PathGlobs, all_files_globs)
        unowned = set(all_files.files) - set(all_owned_sources)

        for dirname, filenames in _group_by_semgrep_dir(unowned).items():
            pt = PutativeTarget.for_target_type(
                SemgrepRuleSourcesGeneratorTarget,
                path=dirname,
                name="semgrep",
                triggering_sources=sorted(filenames),
            )

            pts.append(pt)

    return PutativeTargets(pts)


def rules():
    return [*collect_rules(), UnionRule(PutativeTargetsRequest, PutativeSemgrepTargetsRequest)]
