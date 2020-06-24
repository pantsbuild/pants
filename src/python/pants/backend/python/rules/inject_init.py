# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass

from pants.engine.fs import Digest, FileContent, InputFilesContent, MergeDigests, Snapshot
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.python.pex_build_util import identify_missing_init_files
from pants.source.source_root import OptionalSourceRoot, SourceRootRequest


@dataclass(frozen=True)
class InjectInitRequest:
    sources_snapshot: Snapshot
    sources_stripped: bool  # True iff sources_snapshot has already had source roots stripped.


@dataclass(frozen=True)
class InitInjectedSnapshot:
    snapshot: Snapshot


@rule
async def inject_missing_init_files(request: InjectInitRequest) -> InitInjectedSnapshot:
    """Ensure that every package has an `__init__.py` file in it.

    This will preserve any `__init__.py` files already in the input snapshot.
    """
    snapshot = request.sources_snapshot
    missing_init_files = identify_missing_init_files(snapshot.files)
    if not missing_init_files:
        return InitInjectedSnapshot(snapshot)

    if not request.sources_stripped:
        # Get rid of any identified-as-missing __init__.py files that are not under a source root.
        missing_init_files_list = list(missing_init_files)
        optional_src_roots = await MultiGet(
            Get(OptionalSourceRoot, SourceRootRequest, SourceRootRequest.for_file(init_file))
            for init_file in missing_init_files_list
        )
        for optional_src_root, init_file in zip(optional_src_roots, missing_init_files_list):
            # If the identified-as-missing __init__.py file is above or at a source root, remove it.
            if (
                optional_src_root.source_root is None
                or optional_src_root.source_root.path == os.path.dirname(init_file)
            ):
                missing_init_files.remove(init_file)

    generated_inits_digest = await Get(
        Digest,
        InputFilesContent(FileContent(path=fp, content=b"") for fp in sorted(missing_init_files)),
    )
    result = await Get(Snapshot, MergeDigests((snapshot.digest, generated_inits_digest)))
    return InitInjectedSnapshot(result)


def rules():
    return [inject_missing_init_files, RootRule(InjectInitRequest)]
