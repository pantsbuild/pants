# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.subsystems.pex_build_util import identify_missing_init_files
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, Digest, Snapshot, InputFilesContent, FileContent
from pants.engine.rules import rule
from pants.engine.selectors import Get


# TODO(#7710): Once this gets fixed, rename this to InitInjectedDigest.
@dataclass(frozen=True)
class InjectedInitDigest:
  directory_digest: Digest


@rule
async def inject_init(snapshot: Snapshot) -> InjectedInitDigest:
  """Ensure that every package has an __init__.py file in it."""
  missing_init_files = tuple(sorted(identify_missing_init_files(snapshot.files)))
  if not missing_init_files:
    return InjectedInitDigest(EMPTY_DIRECTORY_DIGEST)
  digest = await Get[Digest](
    InputFilesContent([FileContent(path=fp, content=b"") for fp in missing_init_files])
  )
  return InjectedInitDigest(digest)


def rules():
  return [
    inject_init,
  ]
