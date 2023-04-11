# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.target_types import (
    GoBinaryMainPackageField,
    GoBinaryTarget,
    GoModTarget,
    GoPackageSourcesField,
    GoPackageTarget,
)
from pants.backend.go.util_rules.binary import GoBinaryMainPackage, GoBinaryMainPackageRequest
from pants.base.specs import AncestorGlobSpec, RawSpecs
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
)
from pants.engine.fs import DigestContents, PathGlobs, Paths
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import UnexpandedTargets
from pants.engine.unions import UnionRule
from pants.util.dirutil import group_by_dir
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativeGoTargetsRequest(PutativeTargetsRequest):
    pass


_package_main_re = re.compile(rb"^package main\s*(//.*)?$", re.MULTILINE)


def has_package_main(content: bytes) -> bool:
    return _package_main_re.search(content) is not None


def has_go_mod_ancestor(dirname: str, all_go_mod_dirs: frozenset[str]) -> bool:
    """We shouldn't add package targets if there is no `go.mod`, as it will cause an error."""
    return any(dirname.startswith(go_mod_dir) for go_mod_dir in all_go_mod_dirs)


async def _find_go_mod_targets(
    all_go_mod_files: set[str], all_owned_sources: AllOwnedSources
) -> list[PutativeTarget]:
    unowned_go_mod_files = all_go_mod_files - set(all_owned_sources)
    return [
        PutativeTarget.for_target_type(
            GoModTarget,
            path=dirname,
            name=None,
            triggering_sources=sorted(filenames),
        )
        for dirname, filenames in group_by_dir(unowned_go_mod_files).items()
    ]


async def _find_cgo_sources(
    path: str, all_owned_sources: AllOwnedSources
) -> tuple[list[str], list[str]]:
    all_files_in_package = await Get(Paths, PathGlobs([str(PurePath(path, "*"))]))
    ext_to_files: dict[str, set[str]] = defaultdict(set)
    for file_path in all_files_in_package.files:
        for ext in GoPackageSourcesField.expected_file_extensions:
            if ext == ".go":
                continue
            if file_path.endswith(ext):
                ext_to_files[ext].add(file_path)

    wildcard_globs: list[str] = []
    files_to_add: list[str] = []
    triggering_files: list[str] = []

    for ext, files in ext_to_files.items():
        wildcard = True
        for file in files:
            if file in all_owned_sources:
                wildcard = False

        base_files = sorted([PurePath(f).name for f in files])
        triggering_files.extend(base_files)

        if wildcard:
            wildcard_globs.append(f"*{ext}")
        else:
            files_to_add.extend(base_files)

    return [*wildcard_globs, *sorted(files_to_add)], sorted(triggering_files)


@dataclass(frozen=True)
class FindPutativeGoPackageTargetRequest:
    dir_path: str
    files: tuple[str, ...]
    all_go_mod_dirs: frozenset[str]


@dataclass(frozen=True)
class FindPutativeGoPackageTargetResult:
    putative_target: PutativeTarget | None


@rule
async def find_putative_go_package_target(
    request: FindPutativeGoPackageTargetRequest,
    all_owned_sources: AllOwnedSources,
) -> FindPutativeGoPackageTargetResult:
    # Ignore paths that have `testdata` or `vendor` in them.
    # From `go help packages`: Note, however, that a directory named vendor that itself
    # contains code is not a vendored package: cmd/vendor would be a command named vendor.
    dirname_parts = PurePath(request.dir_path).parts
    if "testdata" in dirname_parts or "vendor" in dirname_parts[0:-1]:
        return FindPutativeGoPackageTargetResult(None)
    if not has_go_mod_ancestor(request.dir_path, request.all_go_mod_dirs):
        return FindPutativeGoPackageTargetResult(None)

    cgo_sources, triggering_cgo_files = await _find_cgo_sources(request.dir_path, all_owned_sources)
    kwargs = {}
    if cgo_sources:
        kwargs = {"sources": ("*.go", *cgo_sources)}

    return FindPutativeGoPackageTargetResult(
        PutativeTarget.for_target_type(
            GoPackageTarget,
            path=request.dir_path,
            name=None,
            kwargs=kwargs,
            triggering_sources=[*sorted(request.files), *triggering_cgo_files],
        )
    )


async def _find_go_package_targets(
    request: PutativeGoTargetsRequest,
    all_go_mod_dirs: frozenset[str],
    all_owned_sources: AllOwnedSources,
) -> list[PutativeTarget]:
    all_go_files = await Get(Paths, PathGlobs, request.path_globs("*.go"))
    unowned_go_files = set(all_go_files.files) - set(all_owned_sources)
    candidate_putative_targets = await MultiGet(
        Get(
            FindPutativeGoPackageTargetResult,
            FindPutativeGoPackageTargetRequest(
                dir_path=dirname,
                files=tuple(filenames),
                all_go_mod_dirs=all_go_mod_dirs,
            ),
        )
        for dirname, filenames in group_by_dir(unowned_go_files).items()
    )
    return [
        ptgt.putative_target
        for ptgt in candidate_putative_targets
        if ptgt.putative_target is not None
    ]


async def _find_go_binary_targets(
    request: PutativeGoTargetsRequest, all_go_mod_dirs: frozenset[str]
) -> list[PutativeTarget]:
    all_go_files_digest_contents = await Get(DigestContents, PathGlobs, request.path_globs("*.go"))

    main_package_dirs = []
    for file_content in all_go_files_digest_contents:
        dirname = os.path.dirname(file_content.path)
        if has_package_main(file_content.content) and has_go_mod_ancestor(dirname, all_go_mod_dirs):
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
    return [
        PutativeTarget.for_target_type(
            GoBinaryTarget,
            path=main_pkg_dir,
            name="bin",
            triggering_sources=tuple(),
        )
        for main_pkg_dir in unowned_main_package_dirs
    ]


@rule(level=LogLevel.DEBUG, desc="Determine candidate Go targets to create")
async def find_putative_go_targets(
    request: PutativeGoTargetsRequest,
    all_owned_sources: AllOwnedSources,
    golang_subsystem: GolangSubsystem,
) -> PutativeTargets:
    putative_targets = []
    _all_go_mod_paths = await Get(Paths, PathGlobs, request.path_globs("go.mod"))
    all_go_mod_files = set(_all_go_mod_paths.files)
    all_go_mod_dirs = frozenset(os.path.dirname(fp) for fp in all_go_mod_files)

    if golang_subsystem.tailor_go_mod_targets:
        putative_targets.extend(await _find_go_mod_targets(all_go_mod_files, all_owned_sources))

    if golang_subsystem.tailor_package_targets:
        putative_targets.extend(
            await _find_go_package_targets(request, all_go_mod_dirs, all_owned_sources)
        )

    if golang_subsystem.tailor_binary_targets:
        putative_targets.extend(await _find_go_binary_targets(request, all_go_mod_dirs))

    return PutativeTargets(putative_targets)


def rules():
    return [*collect_rules(), UnionRule(PutativeTargetsRequest, PutativeGoTargetsRequest)]
