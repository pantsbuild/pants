# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from dataclasses import dataclass
from pathlib import PurePath

from pants.core.util_rules.strip_source_roots import SourceRootStrippedSources, StripSnapshotRequest
from pants.engine.fs import EMPTY_SNAPSHOT, PathGlobs, Snapshot
from pants.engine.rules import rule
from pants.engine.selectors import Get
from pants.python.pex_build_util import identify_missing_ancestor_files
from pants.source.source_root import AllSourceRoots
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
    sources_stripped: bool  # True iff snapshot has already had source roots stripped.


@dataclass(frozen=True)
class AncestorFiles:
    """Any ancestor files found."""

    snapshot: Snapshot


@rule
async def find_missing_ancestor_files(
    request: AncestorFilesRequest, all_source_roots: AllSourceRoots
) -> AncestorFiles:
    """Find any named ancestor files that exist on the filesystem but are not in the snapshot."""
    missing_ancestor_files = identify_missing_ancestor_files(request.name, request.snapshot.files)
    if not missing_ancestor_files:
        return AncestorFiles(EMPTY_SNAPSHOT)

    if request.sources_stripped:
        # If files are stripped, we don't know what source root they might live in, so we look
        # up every source root.
        roots = tuple(root.path for root in all_source_roots)
        missing_ancestor_files = FrozenOrderedSet(
            PurePath(root, f).as_posix()
            for root, f in itertools.product(roots, missing_ancestor_files)
        )

    # NB: This will intentionally _not_ error on any unmatched globs.
    discovered_ancestors_snapshot = await Get(Snapshot, PathGlobs(missing_ancestor_files))
    if request.sources_stripped:
        # We must now strip all discovered paths.
        stripped_snapshot = await Get(
            SourceRootStrippedSources, StripSnapshotRequest(discovered_ancestors_snapshot)
        )
        discovered_ancestors_snapshot = stripped_snapshot.snapshot

    return AncestorFiles(discovered_ancestors_snapshot)


def rules():
    return [find_missing_ancestor_files]
