# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.python.subsystems.pex_build_util import identify_missing_init_files
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, Digest, Snapshot
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.rules import rule
from pants.engine.selectors import Get
from pants.util.objects import datatype


class InitInjectedDigest(datatype([('directory_digest', Digest)])): pass


@rule(InitInjectedDigest, [Snapshot])
def inject_init(snapshot):
  """Ensure that every package has an __init__.py file in it."""
  missing_init_files = tuple(sorted(identify_missing_init_files(snapshot.files)))
  if not missing_init_files:
    new_init_files_digest = EMPTY_DIRECTORY_DIGEST
  else:
    # TODO(7718): add a builtin rule for FilesContent->Snapshot.
    touch_init_request = ExecuteProcessRequest(
      argv=("/usr/bin/touch",) + missing_init_files,
      output_files=missing_init_files,
      description="Inject empty __init__.py into all packages without one already.",
      input_files=snapshot.directory_digest,
    )
    touch_init_result = yield Get(ExecuteProcessResult, ExecuteProcessRequest, touch_init_request)
    new_init_files_digest = touch_init_result.output_directory_digest
  # TODO: get this to work. Likely related to https://github.com/pantsbuild/pants/issues/7710.
  # merged_digest = yield Get(
  #   Digest,
  #   MergedDirectories(directories=(digest, new_init_files_digest))
  # )
  yield InitInjectedDigest(directory_digest=new_init_files_digest)


def rules():
  return [
      inject_init,
    ]
