# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.fs import Digest, FileContent, InputFilesContent, MergeDigests, Snapshot
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get
from pants.python.pex_build_util import identify_missing_init_files


# NB: Needed due to graph ambiguity.
@dataclass(frozen=True)
class InjectInitRequest:
    # NB: This must contain sources already stripped of their source roots.
    stripped_sources_snapshot: Snapshot


@dataclass(frozen=True)
class InitInjectedSnapshot:
    snapshot: Snapshot


@rule
async def inject_missing_init_files(request: InjectInitRequest) -> InitInjectedSnapshot:
    """Ensure that every package has an `__init__.py` file in it.

    This will preserve any `__init__.py` files already in the input snapshot.
    """
    snapshot = request.stripped_sources_snapshot
    missing_init_files = sorted(identify_missing_init_files(snapshot.files))
    if not missing_init_files:
        return InitInjectedSnapshot(snapshot)
    generated_inits_digest = await Get[Digest](
        InputFilesContent(FileContent(path=fp, content=b"") for fp in missing_init_files)
    )
    result = await Get[Snapshot](MergeDigests((snapshot.digest, generated_inits_digest)))
    return InitInjectedSnapshot(result)


def rules():
    return [inject_missing_init_files, RootRule(InjectInitRequest)]
