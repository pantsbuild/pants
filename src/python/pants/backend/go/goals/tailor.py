# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.go.target_types import (
    GoBinaryMainPackage,
    GoBinaryMainPackageField,
    GoBinaryMainPackageRequest,
    GoBinaryTarget,
    GoModTarget,
    GoPackageTarget,
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

    all_go_mod_files, all_go_files, all_go_files_digest_contents = await MultiGet(
        Get(Paths, PathGlobs, request.search_paths.path_globs("go.mod")),
        Get(Paths, PathGlobs, request.search_paths.path_globs("*.go")),
        Get(DigestContents, PathGlobs, request.search_paths.path_globs("*.go")),
    )

    # Add `go_mod` targets.
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

    # Add `go_package` targets.
    unowned_go_files = set(all_go_files.files) - set(all_owned_sources)
    for dirname, filenames in group_by_dir(unowned_go_files).items():
        # Ignore paths that have `testdata` or `vendor` in them.
        # From `go help packages`: Note, however, that a directory named vendor that itself contains code
        # is not a vendored package: cmd/vendor would be a command named vendor.
        dirname_parts = PurePath(dirname).parts
        if "testdata" in dirname_parts or "vendor" in dirname_parts[0:-1]:
            continue
        putative_targets.append(
            PutativeTarget.for_target_type(
                GoPackageTarget,
                path=dirname,
                name=None,
                triggering_sources=sorted(filenames),
            )
        )

    # Add `go_binary` targets.
    main_package_dirs = [
        os.path.dirname(file_content.path)
        for file_content in all_go_files_digest_contents
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
        # NB: We assume the `go_package` lives in the directory it's defined, which we validate
        # by e.g. banning `**` in its sources field.
        pkg.address.spec_path
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
