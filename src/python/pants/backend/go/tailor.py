# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import itertools
import os
from dataclasses import dataclass
from typing import Dict, List

from pants.backend.go.module import ResolvedGoModule, ResolveGoModuleRequest
from pants.backend.go.pkg import (
    ResolvedGoPackage,
    ResolveExternalGoModuleToPackagesRequest,
    ResolveExternalGoModuleToPackagesResult,
)
from pants.backend.go.target_types import (
    GoExternalModule,
    GoExtModPackage,
    GoModule,
    GoModuleSources,
    GoPackage,
)
from pants.base.specs import AddressSpecs, MaybeEmptyDescendantAddresses, MaybeEmptySiblingAddresses
from pants.build_graph.address import Address
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
    group_by_dir,
)
from pants.engine.fs import PathGlobs, Paths
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import UnexpandedTargets
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


def compute_go_external_module_target_name(name: str, version: str) -> str:
    return f"{name.replace('/', '_')}_{version}"


@dataclass(frozen=True)
class PutativeGoExternalModuleTargetsRequest(PutativeTargetsRequest):
    pass


@rule(level=LogLevel.DEBUG, desc="Determine candidate Go `go_external_module` targets to create")
async def find_putative_go_external_module_targets(
    request: PutativeGoExternalModuleTargetsRequest, _all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    # Unlike ordinary tailor invocations, this rule looks at existing `go_module` targets and not at actual
    # source files because it infers `go_external_module` targets based on go.mod contents. (This may require
    # invoking `tailor` first to create `go_module` targets and then again to create `go_external_module`
    # targets.)
    #
    # TODO: This might better work as a BUILD macro if https://github.com/pantsbuild/pants/issues/7022 is
    # resolved and macros are able to invoke the engine or processes.

    addresses = itertools.chain.from_iterable(
        [
            [MaybeEmptySiblingAddresses(search_path), MaybeEmptyDescendantAddresses(search_path)]
            for search_path in request.search_paths.dirs
        ]
    )
    candidate_targets = await Get(UnexpandedTargets, AddressSpecs(addresses))
    go_module_targets = [
        tgt
        for tgt in candidate_targets
        if tgt.has_field(GoModuleSources) and not tgt.address.is_file_target
    ]

    putative_targets = []

    resolved_go_modules = await MultiGet(
        Get(ResolvedGoModule, ResolveGoModuleRequest(go_module_target.address))
        for go_module_target in go_module_targets
    )

    # TODO: Figure out a MultiGet here. (Would be nice if MultiGet could operate on dictionaries.)
    resolved_ext_mod_packages: Dict[Address, List[ResolvedGoPackage]] = {}
    for resolved_go_module in resolved_go_modules:
        resolved_ext_mod_packages[resolved_go_module.target.address] = []
        for module_descriptor in resolved_go_module.modules:
            result = await Get(
                ResolveExternalGoModuleToPackagesResult,
                ResolveExternalGoModuleToPackagesRequest(
                    path=module_descriptor.module_path,
                    version=module_descriptor.module_version,
                ),
            )
            resolved_ext_mod_packages[resolved_go_module.target.address] += result.packages

    for resolved_go_module in resolved_go_modules:
        for module_descriptor in resolved_go_module.modules:
            putative_targets.append(
                PutativeTarget.for_target_type(
                    GoExternalModule,
                    resolved_go_module.target.address.spec_path,
                    compute_go_external_module_target_name(
                        module_descriptor.module_path, module_descriptor.module_version
                    ),
                    [],
                    kwargs={
                        "path": module_descriptor.module_path,
                        "version": module_descriptor.module_version,
                        "import_path": module_descriptor.import_path,
                    },
                    build_file_name="BUILD.godeps",
                    comments=(
                        "Auto-generated by `./pants tailor`. Re-run `./pants tailor` if go.mod changes.",
                    ),
                )
            )

    for address, packages in resolved_ext_mod_packages.items():
        for i, package in enumerate(packages):
            assert package.module_path
            assert package.module_version
            ext_mod_target_name = compute_go_external_module_target_name(
                package.module_path, package.module_version
            )
            target_name = f"{ext_mod_target_name}-{i}"  # TODO: append subpath in module instead
            putative_targets.append(
                PutativeTarget.for_target_type(
                    GoExtModPackage,
                    address.spec_path,
                    target_name,
                    [],
                    kwargs={
                        "path": package.module_path,
                        "version": package.module_version,
                        "import_path": package.import_path,
                    },
                    build_file_name="BUILD.godeps",
                    comments=(
                        "Auto-generated by `./pants tailor`. Re-run `./pants tailor` if go.mod changes.",
                    ),
                )
            )

    return PutativeTargets(putative_targets)


def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativeGoPackageTargetsRequest),
        UnionRule(PutativeTargetsRequest, PutativeGoModuleTargetsRequest),
        UnionRule(PutativeTargetsRequest, PutativeGoExternalModuleTargetsRequest),
    ]
