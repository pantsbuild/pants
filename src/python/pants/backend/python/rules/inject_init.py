# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from dataclasses import dataclass
from pathlib import PurePath

from pants.core.util_rules.strip_source_roots import SourceRootStrippedSources, StripSnapshotRequest
from pants.engine.fs import MergeDigests, PathGlobs, Snapshot
from pants.engine.rules import rule
from pants.engine.selectors import Get
from pants.python.pex_build_util import identify_missing_init_files
from pants.source.source_root import AllSourceRoots
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class InjectInitRequest:
    snapshot: Snapshot
    sources_stripped: bool  # True iff snapshot has already had source roots stripped.


@dataclass(frozen=True)
class InitInjectedSnapshot:
    snapshot: Snapshot


@rule
async def inject_missing_init_files(
    request: InjectInitRequest, all_source_roots: AllSourceRoots
) -> InitInjectedSnapshot:
    """Add any `__init__.py` files that exist on the filesystem but are not yet in the snapshot."""
    missing_init_files = identify_missing_init_files(request.snapshot.files)
    if not missing_init_files:
        return InitInjectedSnapshot(request.snapshot)

    if request.sources_stripped:
        # If files are stripped, we don't know what source root they might live in, so we look
        # up every source root.
        roots = tuple(root.path for root in all_source_roots)
        missing_init_files = FrozenOrderedSet(
            PurePath(root, f).as_posix() for root, f in itertools.product(roots, missing_init_files)
        )

    # NB: This will intentionally _not_ error on any unmatched globs.
    discovered_inits_snapshot = await Get(Snapshot, PathGlobs(missing_init_files))
    if request.sources_stripped:
        # We must now strip all discovered paths.
        stripped_snapshot = await Get(
            SourceRootStrippedSources, StripSnapshotRequest(discovered_inits_snapshot)
        )
        discovered_inits_snapshot = stripped_snapshot.snapshot

    result = await Get(
        Snapshot, MergeDigests((request.snapshot.digest, discovered_inits_snapshot.digest)),
    )
    return InitInjectedSnapshot(result)


def rules():
    return [inject_missing_init_files]
