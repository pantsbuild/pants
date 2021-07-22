# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass

from pants.backend.terraform.target_types import TerraformModule
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
class PutativeTerraformTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate Terraform targets to create")
async def find_putative_targets(
    request: PutativeTerraformTargetsRequest, all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    all_terraform_files = await Get(Paths, PathGlobs, request.search_paths.path_globs("*.tf"))
    unowned_terraform_files = set(all_terraform_files.files) - set(all_owned_sources)

    putative_targets = []
    for dirname, filenames in group_by_dir(unowned_terraform_files).items():
        putative_targets.append(
            PutativeTarget.for_target_type(
                TerraformModule,
                dirname,
                os.path.basename(dirname),
                sorted(filenames),
            )
        )

    return PutativeTargets(putative_targets)


def rules():
    return [*collect_rules(), UnionRule(PutativeTargetsRequest, PutativeTerraformTargetsRequest)]
