# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.backend.python.dependency_inference.module_mapper import PythonModule
from pants.backend.python.target_types import (
    PexBinary,
    PexEntryPointField,
    PythonLibrary,
    PythonTests,
    PythonTestsSources,
    ResolvedPexEntryPoint,
    ResolvePexEntryPointRequest,
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
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Target, UnexpandedTargets
from pants.engine.unions import UnionRule
from pants.python.python_setup import PythonSetup
from pants.source.filespec import Filespec, matches_filespec
from pants.source.source_root import SourceRootsRequest, SourceRootsResult
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PutativePythonTargetsRequest(PutativeTargetsRequest):
    pass


def classify_source_files(paths: Iterable[str]) -> dict[type[Target], set[str]]:
    """Returns a dict of target type -> files that belong to targets of that type."""
    tests_filespec = Filespec(includes=list(PythonTestsSources.default))
    test_filenames = set(
        matches_filespec(tests_filespec, paths=[os.path.basename(path) for path in paths])
    )
    test_files = {path for path in paths if os.path.basename(path) in test_filenames}
    library_files = set(paths) - test_files
    return {PythonTests: test_files, PythonLibrary: library_files}


# The order "__main__" == __name__ would also technically work, but is very
# non-idiomatic, so we ignore it.
_entry_point_re = re.compile(rb"^if __name__ +== +['\"]__main__['\"]: *(#.*)?$", re.MULTILINE)


def is_entry_point(content: bytes) -> bool:
    # Identify files that look like entry points.  We use a regex for speed, as it will catch
    # almost all correct cases in practice, with extremely rare false positives (we will only
    # have a false positive if the matching code is in a multiline string indented all the way
    # to the left). Looking at the ast would be more correct, technically, but also more laborious,
    # trickier to implement correctly for different interpreter versions, and much slower.
    return _entry_point_re.search(content) is not None


@rule(level=LogLevel.DEBUG, desc="Determine candidate Python targets to create")
async def find_putative_targets(
    req: PutativePythonTargetsRequest,
    all_owned_sources: AllOwnedSources,
    python_setup: PythonSetup,
) -> PutativeTargets:
    # Find library/test targets.

    all_py_files_globs: PathGlobs = req.search_paths.path_globs("*.py")
    all_py_files = await Get(Paths, PathGlobs, all_py_files_globs)
    unowned_py_files = set(all_py_files.files) - set(all_owned_sources)
    classified_unowned_py_files = classify_source_files(unowned_py_files)
    pts = []
    for tgt_type, paths in classified_unowned_py_files.items():
        for dirname, filenames in group_by_dir(paths).items():
            name = "tests" if tgt_type == PythonTests else os.path.basename(dirname)
            kwargs = {"name": name} if tgt_type == PythonTests else {}
            if (
                python_setup.tailor_ignore_solitary_init_files
                and tgt_type == PythonLibrary
                and filenames == {"__init__.py"}
            ):
                continue
            pts.append(
                PutativeTarget.for_target_type(
                    tgt_type, dirname, name, sorted(filenames), kwargs=kwargs
                )
            )

    if python_setup.tailor_pex_binary_targets:
        # Find binary targets.

        # Get all files whose content indicates that they are entry points.
        digest_contents = await Get(DigestContents, PathGlobs, all_py_files_globs)
        entry_points = [
            file_content.path
            for file_content in digest_contents
            if is_entry_point(file_content.content)
        ]

        # Get the modules for these entry points.
        src_roots = await Get(
            SourceRootsResult, SourceRootsRequest, SourceRootsRequest.for_files(entry_points)
        )
        module_to_entry_point = {}
        for entry_point in entry_points:
            entry_point_path = PurePath(entry_point)
            src_root = src_roots.path_to_root[entry_point_path]
            stripped_entry_point = entry_point_path.relative_to(src_root.path)
            module = PythonModule.create_from_stripped_path(stripped_entry_point)
            module_to_entry_point[module.module] = entry_point

        # Get existing binary targets for these entry points.
        entry_point_dirs = {os.path.dirname(entry_point) for entry_point in entry_points}
        possible_existing_binary_targets = await Get(
            UnexpandedTargets, AddressSpecs(AscendantAddresses(d) for d in entry_point_dirs)
        )
        possible_existing_binary_entry_points = await MultiGet(
            Get(ResolvedPexEntryPoint, ResolvePexEntryPointRequest(t[PexEntryPointField]))
            for t in possible_existing_binary_targets
            if t.has_field(PexEntryPointField)
        )
        possible_existing_entry_point_modules = {
            rep.val.module for rep in possible_existing_binary_entry_points if rep.val
        }
        unowned_entry_point_modules = (
            module_to_entry_point.keys() - possible_existing_entry_point_modules
        )

        # Generate new targets for entry points that don't already have one.
        for entry_point_module in unowned_entry_point_modules:
            entry_point = module_to_entry_point[entry_point_module]
            path, fname = os.path.split(entry_point)
            name = os.path.splitext(fname)[0]
            pts.append(
                PutativeTarget.for_target_type(
                    target_type=PexBinary,
                    path=path,
                    name=name,
                    triggering_sources=tuple(),
                    kwargs={"name": name, "entry_point": fname},
                )
            )

    return PutativeTargets(pts)


def rules():
    return [
        *collect_rules(),
        UnionRule(PutativeTargetsRequest, PutativePythonTargetsRequest),
    ]
