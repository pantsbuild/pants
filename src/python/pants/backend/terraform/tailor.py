# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass

from pants.backend.terraform.target_types import TerraformModules
from pants.core.goals.tailor import PutativeTarget, PutativeTargets, PutativeTargetsRequest
from pants.engine.fs import PathGlobs, Paths
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeTerraformTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate Terraform targets to create")
async def find_putative_targets(request: PutativeTerraformTargetsRequest) -> PutativeTargets:
    putative_targets = []

    all_terraform_files = await Get(Paths, PathGlobs, request.search_paths.path_globs("*.tf"))
    if all_terraform_files:
        # Add a terraform_modules() top-level generator target if any Terraform files are present.
        putative_targets.append(
            PutativeTarget.for_target_type(
                TerraformModules,
                "",
                "tf_mods",
                [os.path.join(search_path, "**/*.tf") for search_path in request.search_paths.dirs],
            )
        )

    return PutativeTargets(putative_targets)


def rules():
    return [*collect_rules(), UnionRule(PutativeTargetsRequest, PutativeTerraformTargetsRequest)]
