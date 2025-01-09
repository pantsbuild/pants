# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass
from typing import List

from pants.backend.terraform.target_types import (
    TerraformBackendTarget,
    TerraformModuleTarget,
    TerraformVarFileTarget,
)
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
async def find_putative_terraform_module_targets(
    request: PutativeTerraformTargetsRequest,
    terraform: TerraformTool,
    all_owned_sources: AllOwnedSources,
) -> PutativeTargets:
    if not terraform.tailor:
        return PutativeTargets()
    putative_targets: List[PutativeTarget] = []

    all_terraform_files = await Get(Paths, PathGlobs, request.path_globs("*.tf"))
    unowned_terraform_files = set(all_terraform_files.files) - set(all_owned_sources)

    putative_targets.extend(
        PutativeTarget.for_target_type(
            TerraformModuleTarget,
            path=dirname,
            name=None,
            triggering_sources=sorted(filenames),
        )
        for dirname, filenames in group_by_dir(unowned_terraform_files).items()
    )

    all_backend_files = await Get(Paths, PathGlobs, request.path_globs("*.tfbackend"))
    unowned_backend_files = set(all_backend_files.files) - set(all_owned_sources)
    for backend_file in unowned_backend_files:
        dirname, filename = os.path.split(backend_file)
        putative_targets.append(
            PutativeTarget.for_target_type(
                TerraformBackendTarget,
                path=dirname,
                name=filename,
                kwargs={"source": filename},
                triggering_sources=(filename,),
            )
        )

    # We generate separate targets for each var file,
    # to not make assumptions that they're all together.
    all_var_files = await Get(Paths, PathGlobs, request.path_globs("*.tfvars"))
    unowned_var_files = set(all_var_files.files) - set(all_owned_sources)
    for var_file in unowned_var_files:
        dirname, filename = os.path.split(var_file)
        putative_targets.append(
            PutativeTarget.for_target_type(
                TerraformVarFileTarget,
                path=dirname,
                name=filename,
                kwargs={"sources": (filename,)},
                triggering_sources=(filename,),
            )
        )

    return PutativeTargets(putative_targets)


def rules():
    return [*collect_rules(), UnionRule(PutativeTargetsRequest, PutativeTerraformTargetsRequest)]
