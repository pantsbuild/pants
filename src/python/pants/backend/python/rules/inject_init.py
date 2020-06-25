# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass

from pants.engine.fs import (
    Digest,
    FileContent,
    InputFilesContent,
    MergeDigests,
    PathGlobs,
    Snapshot,
)
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.python.pex_build_util import identify_missing_init_files
from pants.source.source_root import OptionalSourceRoot, SourceRootRequest
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class InjectInitRequest:
    snapshot: Snapshot
    sources_stripped: bool  # True iff sources_snapshot has already had source roots stripped.


@dataclass(frozen=True)
class InitInjectedSnapshot:
    snapshot: Snapshot


@rule
async def inject_missing_init_files(request: InjectInitRequest) -> InitInjectedSnapshot:
    """Ensure that every package has an `__init__.py` file in it.

    This will first use any `__init__.py` files in the input snapshot, then read from the filesystem
    to see if any exist but are not in the snapshot, and finally will create empty files.
    """
    original_missing_init_files = identify_missing_init_files(request.snapshot.files)
    if not original_missing_init_files:
        return InitInjectedSnapshot(request.snapshot)

    missing_init_files = original_missing_init_files
    if not request.sources_stripped:
        # Get rid of any identified-as-missing __init__.py files that are not under a source root.
        optional_src_roots = await MultiGet(
            Get(OptionalSourceRoot, SourceRootRequest, SourceRootRequest.for_file(init_file))
            for init_file in original_missing_init_files
        )

        def is_under_source_root(init_file: str, optional_src_root: OptionalSourceRoot) -> bool:
            return (
                optional_src_root.source_root is not None
                and optional_src_root.source_root.path != os.path.dirname(init_file)
            )

        missing_init_files = FrozenOrderedSet(
            init_file
            for init_file, optional_src_root in zip(original_missing_init_files, optional_src_roots)
            if is_under_source_root(init_file, optional_src_root)
        )

    discovered_inits_snapshot = await Get(Snapshot, PathGlobs(missing_init_files))
    generated_inits_digest = await Get(
        Digest,
        InputFilesContent(
            FileContent(fp, b"# Generated `__init__.py` file.")
            for fp in missing_init_files.difference(discovered_inits_snapshot.files)
        ),
    )
    result = await Get(
        Snapshot,
        MergeDigests(
            (request.snapshot.digest, discovered_inits_snapshot.digest, generated_inits_digest)
        ),
    )
    return InitInjectedSnapshot(result)


def rules():
    return [inject_missing_init_files, RootRule(InjectInitRequest)]
