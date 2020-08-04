# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from typing import Sequence, Set

from pants.engine.fs import EMPTY_SNAPSHOT, PathGlobs, Snapshot
from pants.engine.rules import Get, collect_rules, rule
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class AncestorFilesRequest:
    """A request for ancestor files of a given name.

    "Ancestor files" for name foobar means all files of that name that are siblings of,
    or in parent directories of, a .py file in the snapshot.

    This is useful when the presence of such ancestor files has semantic meaning.
    For example, ancestor __init__.py files denote packages, and ancestor conftest.py
    files denote pytest configuration.

    This allows us to pull in these files without requiring explicit or implicit
    dependencies on them.
    """

    name: str
    snapshot: Snapshot


@dataclass(frozen=True)
class AncestorFiles:
    """Any ancestor files found."""

    snapshot: Snapshot


def identify_missing_ancestor_files(name: str, sources: Sequence[str]) -> FrozenOrderedSet[str]:
    """Return the paths of potentially missing ancestor files.

    NB: The sources are expected to not have had their source roots stripped.
    Therefore this function will consider superfluous files at and above the source roots,
    (e.g., src/python/<name>, src/<name>). It is the caller's responsibility to filter these
    out if necessary.
    """
    packages: Set[str] = set()
    for source in sources:
        if not source.endswith(".py"):
            continue
        pkg_dir = os.path.dirname(source)
        if not pkg_dir or pkg_dir in packages:
            continue
        package = ""
        for component in pkg_dir.split(os.sep):
            package = os.path.join(package, component)
            packages.add(package)

    return FrozenOrderedSet(
        sorted({os.path.join(package, name) for package in packages} - set(sources))
    )


@rule
async def find_missing_ancestor_files(request: AncestorFilesRequest) -> AncestorFiles:
    """Find any named ancestor files that exist on the filesystem but are not in the snapshot."""
    missing_ancestor_files = identify_missing_ancestor_files(request.name, request.snapshot.files)
    if not missing_ancestor_files:
        return AncestorFiles(EMPTY_SNAPSHOT)

    # NB: This will intentionally _not_ error on any unmatched globs.
    discovered_ancestors_snapshot = await Get(Snapshot, PathGlobs(missing_ancestor_files))
    return AncestorFiles(discovered_ancestors_snapshot)


def rules():
    return collect_rules()
