# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.target_types import (
    GoBinaryMainPackage,
    GoBinaryMainPackageField,
    GoBinaryMainPackageRequest,
    GoBinaryTarget,
    GoModTarget,
    GoPackageTarget,
)
from pants.base.specs import AncestorGlobSpec, RawSpecs
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


def has_go_mod_ancestor(dirname: str, all_go_mod_dirs: set[str]) -> bool:
    """We shouldn't add package targets if there is no `go.mod`, as it will cause an error."""
    return any(dirname.startswith(go_mod_dir) for go_mod_dir in all_go_mod_dirs)


@rule(level=LogLevel.DEBUG, desc="Determine candidate Go targets to create")
async def find_putative_go_targets(
    request: PutativeGoTargetsRequest,
    all_owned_sources: AllOwnedSources,
    golang_subsystem: GolangSubsystem,
) -> PutativeTargets:
    putative_targets = []
    _all_go_mod_paths = await Get(Paths, PathGlobs, request.path_globs("go.mod"))
    all_go_mod_files = set(_all_go_mod_paths.files)
    all_go_mod_dirs = {os.path.dirname(fp) for fp in all_go_mod_files}

    if golang_subsystem.tailor_go_mod_targets:
        unowned_go_mod_files = all_go_mod_files - set(all_owned_sources)
        for dirname, filenames in group_by_dir(unowned_go_mod_files).items():
            putative_targets.append(
                PutativeTarget.for_target_type(
                    GoModTarget,
                    path=dirname,
                    name=None,
                    triggering_sources=sorted(filenames),
                )
            )

    if golang_subsystem.tailor_package_targets:
        all_go_files = await Get(Paths, PathGlobs, request.path_globs("*.go"))
        unowned_go_files = set(all_go_files.files) - set(all_owned_sources)
        for dirname, filenames in group_by_dir(unowned_go_files).items():
            # Ignore paths that have `testdata` or `vendor` in them.
            # From `go help packages`: Note, however, that a directory named vendor that itself
            # contains code is not a vendored package: cmd/vendor would be a command named vendor.
            dirname_parts = PurePath(dirname).parts
            if "testdata" in dirname_parts or "vendor" in dirname_parts[0:-1]:
                continue
            if not has_go_mod_ancestor(dirname, all_go_mod_dirs):
                continue
            putative_targets.append(
                PutativeTarget.for_target_type(
                    GoPackageTarget,
                    path=dirname,
                    name=None,
                    triggering_sources=sorted(filenames),
                )
            )

    if golang_subsystem.tailor_binary_targets:
        all_go_files_digest_contents = await Get(
            DigestContents, PathGlobs, request.path_globs("*.go")
        )

        main_package_dirs = []
        for file_content in all_go_files_digest_contents:
            dirname = os.path.dirname(file_content.path)
            if has_package_main(file_content.content) and has_go_mod_ancestor(
                dirname, all_go_mod_dirs
            ):
                main_package_dirs.append(dirname)

        existing_targets = await Get(
            UnexpandedTargets,
            RawSpecs(
                ancestor_globs=tuple(AncestorGlobSpec(d) for d in main_package_dirs),
                description_of_origin="the `go_binary` tailor rule",
            ),
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
