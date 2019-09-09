# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.pex_build_util import identify_missing_init_files
from pants.engine.fs import (EMPTY_DIRECTORY_DIGEST, Digest, FileContent, FilesContent, Snapshot,
                             InputFilesContent)
from pants.engine.rules import rule
from pants.engine.selectors import Get
from pants.util.objects import datatype


# TODO(#7710): Once this gets fixed, rename this to InitInjectedDigest.
class InjectedInitDigest(datatype([('directory_digest', Digest)])): pass


@rule(InjectedInitDigest, [Snapshot])
def inject_init(snapshot):
  """Ensure that every package has an __init__.py file in it."""
  missing_init_files = tuple(sorted(identify_missing_init_files(snapshot.files)))
  if not missing_init_files:
    new_init_files_digest = EMPTY_DIRECTORY_DIGEST
  else:
    new_init_files_digest = yield Get(Digest, InputFilesContent(FilesContent(tuple(
      FileContent(
        path=path,
        content=b'',
      ) for path in missing_init_files
    ))))
  # TODO(#7710): Once this gets fixed, merge the original source digest and the new init digest
  # into one unified digest.
  yield InjectedInitDigest(directory_digest=new_init_files_digest)


def rules():
  return [
      inject_init,
    ]
