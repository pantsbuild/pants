# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass

from pants.backend.go.target_types import GoModule, GoPackage
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
class PutativeGoPackageTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate Go `go_package` targets to create")
async def find_putative_go_package_targets(
    request: PutativeGoPackageTargetsRequest, all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    all_go_files = await Get(Paths, PathGlobs, request.search_paths.path_globs("*.go"))
    unowned_go_files = set(all_go_files.files) - set(all_owned_sources)

    putative_targets = []
    for dirname, filenames in group_by_dir(unowned_go_files).items():
        putative_targets.append(
            PutativeTarget.for_target_type(
                GoPackage,
                dirname,
                os.path.basename(dirname),
                sorted(filenames),
            )
        )

    return PutativeTargets(putative_targets)


@dataclass(frozen=True)
class PutativeGoModuleTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate Go `go_module` targets to create")
async def find_putative_go_module_targets(
    request: PutativeGoModuleTargetsRequest, all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    all_go_mod_files = await Get(Paths, PathGlobs, request.search_paths.path_globs("go.mod"))
    unowned_go_mod_files = set(all_go_mod_files.files) - set(all_owned_sources)

    putative_targets = []
    for dirname, filenames in group_by_dir(unowned_go_mod_files).items():
        putative_targets.append(
            PutativeTarget.for_target_type(
                GoModule,
                dirname,
                os.path.basename(dirname),
                sorted(filenames),
            )
        )

    return PutativeTargets(putative_targets)


def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeGoPackageTargetsRequest),
        UnionRule(PutativeTargetsRequest, PutativeGoModuleTargetsRequest),
    ]
