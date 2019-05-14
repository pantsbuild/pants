# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.python.subsystems.pex_build_util import identify_missing_init_files
from pants.engine.fs import Digest, EMPTY_DIRECTORY_DIGEST, FilesContent, MergedDirectories, Snapshot
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.rules import rule
from pants.engine.selectors import Get
from pants.util.objects import datatype


class InitInjectedDigest(datatype([('digest', Digest)])): pass


# TODO(7716): change this signature to take a Snapshot once we add a builtin rule Digest->Snapshot.
@rule(InitInjectedDigest, [Digest])
def inject_init(digest):
  """Ensure that every package has an __init__.py file in it."""
  file_contents = yield Get(FilesContent, Digest, digest)
  file_paths = [fc.path for fc in file_contents]
  missing_init_files = tuple(sorted(identify_missing_init_files(file_paths)))
  if not missing_init_files:
    new_init_files_digest = EMPTY_DIRECTORY_DIGEST
  else:
    # TODO(7718): add a builtin rule for FilesContent->Snapshot.
    touch_init_request = ExecuteProcessRequest(
      argv=("/usr/bin/touch",) + missing_init_files,
      output_files=missing_init_files,
      description="Inject empty __init__.py into all packages without one already.",
      input_files=digest,
    )
    touch_init_result = yield Get(ExecuteProcessResult, ExecuteProcessRequest, touch_init_request)
    new_init_files_digest = touch_init_result.output_directory_digest
  merged_digest = Get(
    Digest,
    MergedDirectories(directories=(digest, new_init_files_digest))
  )
  yield merged_digest


def rules():
  return [
      inject_init,
    ]
