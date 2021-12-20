# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from pants.backend.go.target_types import (
    GoBinaryMainPackage,
    GoBinaryMainPackageField,
    GoBinaryMainPackageRequest,
    GoBinaryTarget,
    GoModTarget,
)
from pants.base.specs import AddressSpecs, AscendantAddresses
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
    group_by_dir,
)
from pants.engine.fs import DigestContents, PathGlobs, Paths
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import UnexpandedTargets
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeGoTargetsRequest(PutativeTargetsRequest):
    pass


_package_main_re = re.compile(rb"^package main\s*(//.*)?$", re.MULTILINE)


def has_package_main(content: bytes) -> bool:
    return _package_main_re.search(content) is not None


@rule(level=LogLevel.DEBUG, desc="Determine candidate Go targets to create")
async def find_putative_go_targets(
    request: PutativeGoTargetsRequest, all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    putative_targets = []

    # Add `go_mod` targets.
    all_go_mod_files = await Get(Paths, PathGlobs, request.search_paths.path_globs("go.mod"))
    unowned_go_mod_files = set(all_go_mod_files.files) - set(all_owned_sources)
    for dirname, filenames in group_by_dir(unowned_go_mod_files).items():
        putative_targets.append(
            PutativeTarget.for_target_type(
                GoModTarget,
                path=dirname,
                name=None,
                triggering_sources=sorted(filenames),
            )
        )

    # Add `go_binary` targets.
    digest_contents = await Get(DigestContents, PathGlobs, request.search_paths.path_globs("*.go"))
    main_package_dirs = [
        os.path.dirname(file_content.path)
        for file_content in digest_contents
        if has_package_main(file_content.content)
    ]
    existing_targets = await Get(
        UnexpandedTargets, AddressSpecs(AscendantAddresses(d) for d in main_package_dirs)
    )
    owned_main_packages = await MultiGet(
        Get(GoBinaryMainPackage, GoBinaryMainPackageRequest(t[GoBinaryMainPackageField]))
        for t in existing_targets
        if t.has_field(GoBinaryMainPackageField)
    )
    unowned_main_package_dirs = set(main_package_dirs) - {
        # We can be confident `go_first_party_package` targets were generated, meaning that the
        # below will get us the full path to the package's directory.
        # TODO: generalize this
        os.path.join(pkg.address.spec_path, pkg.address.generated_name[2:]).rstrip("/")  # type: ignore[index]
        for pkg in owned_main_packages
    }
    putative_targets.extend(
        PutativeTarget.for_target_type(
            GoBinaryTarget,
            path=main_pkg_dir,
            name="bin",
            triggering_sources=tuple(),
        )
        for main_pkg_dir in unowned_main_package_dirs
    )

    return PutativeTargets(putative_targets)


def rules():
    return [*collect_rules(), UnionRule(PutativeTargetsRequest, PutativeGoTargetsRequest)]
