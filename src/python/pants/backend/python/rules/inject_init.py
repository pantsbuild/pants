# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.rules.inject_ancestor_files import AncestorFiles, AncestorFilesRequest
from pants.engine.fs import MergeDigests, Snapshot
from pants.engine.rules import rule
from pants.engine.selectors import Get


@dataclass(frozen=True)
class InjectInitRequest:
    snapshot: Snapshot
    sources_stripped: bool  # True iff snapshot has already had source roots stripped.


@dataclass(frozen=True)
class InitInjectedSnapshot:
    snapshot: Snapshot


@rule
async def inject_missing_init_files(request: InjectInitRequest) -> InitInjectedSnapshot:
    extra_init_files = await Get(
        AncestorFiles,
        AncestorFilesRequest("__init__.py", request.snapshot, request.sources_stripped),
    )
    result = await Get(
        Snapshot, MergeDigests((request.snapshot.digest, extra_init_files.snapshot.digest)),
    )
    return InitInjectedSnapshot(result)


def rules():
    return [inject_missing_init_files]
