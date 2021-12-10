# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass

from pants.engine.fs import EMPTY_SNAPSHOT, PathGlobs, Snapshot
from pants.engine.rules import Get, collect_rules, rule


@dataclass(frozen=True)
class AncestorFilesRequest:
    """A request for ancestor files of the given names.

    "Ancestor files" means all files with one of the given names that are siblings of, or in parent
    directories of, a `.py` or `.pyi` file in the input_files.
    """

    input_files: tuple[str, ...]
    requested: tuple[str, ...]


@dataclass(frozen=True)
class AncestorFiles:
    """Any ancestor files found."""

    snapshot: Snapshot


def putative_ancestor_files(input_files: tuple[str, ...], requested: tuple[str, ...]) -> set[str]:
    """Return the paths of potentially missing ancestor files.

    NB: The sources are expected to not have had their source roots stripped.
    Therefore this function will consider superfluous files at and above the source roots,
    (e.g., src/python/<name>, src/<name>). It is the caller's responsibility to filter these
    out if necessary.
    """
    packages: set[str] = set()
    for input_file in input_files:
        if not input_file.endswith((".py", ".pyi")):
            continue
        pkg_dir = os.path.dirname(input_file)
        if pkg_dir in packages:
            continue
        package = ""
        packages.add(package)
        for component in pkg_dir.split(os.sep):
            package = os.path.join(package, component)
            packages.add(package)

    return {
        os.path.join(package, requested_f) for package in packages for requested_f in requested
    } - set(input_files)


@rule
async def find_ancestor_files(request: AncestorFilesRequest) -> AncestorFiles:
    putative = putative_ancestor_files(request.input_files, request.requested)
    if not putative:
        return AncestorFiles(EMPTY_SNAPSHOT)

    # NB: This will intentionally _not_ error on any unmatched globs.
    discovered_ancestors_snapshot = await Get(Snapshot, PathGlobs(putative))
    return AncestorFiles(discovered_ancestors_snapshot)


def rules():
    return collect_rules()
