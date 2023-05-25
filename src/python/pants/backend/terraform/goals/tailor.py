# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.terraform.target_types import TerraformModuleTarget
from pants.backend.terraform.tool import TerraformTool
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
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeTerraformTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate Terraform targets to create")
async def find_putative_terrform_module_targets(
    request: PutativeTerraformTargetsRequest,
    terraform: TerraformTool,
    all_owned_sources: AllOwnedSources,
) -> PutativeTargets:
    if not terraform.tailor:
        return PutativeTargets()

    all_terraform_files = await Get(Paths, PathGlobs, request.path_globs("*.tf"))
    unowned_terraform_files = set(all_terraform_files.files) - set(all_owned_sources)

    putative_targets = [
        PutativeTarget.for_target_type(
            TerraformModuleTarget,
            path=dirname,
            name=None,
            triggering_sources=sorted(filenames),
        )
        for dirname, filenames in group_by_dir(unowned_terraform_files).items()
    ]

    return PutativeTargets(putative_targets)


def rules():
    return [*collect_rules(), UnionRule(PutativeTargetsRequest, PutativeTerraformTargetsRequest)]
