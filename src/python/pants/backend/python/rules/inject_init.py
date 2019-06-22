# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.pex_build_util import identify_missing_init_files
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, Digest, Snapshot
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
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
    # TODO(7718): add a builtin rule for FilesContent->Snapshot, so that we can avoid using touch
    # and the absolute path and have the engine build the files for us.
    touch_init_request = ExecuteProcessRequest(
      argv=("/usr/bin/touch",) + missing_init_files,
      output_files=missing_init_files,
      description="Inject missing __init__.py files: {}".format(", ".join(missing_init_files)),
      input_files=snapshot.directory_digest,
    )
    touch_init_result = yield Get(ExecuteProcessResult, ExecuteProcessRequest, touch_init_request)
    new_init_files_digest = touch_init_result.output_directory_digest
  # TODO(#7710): Once this gets fixed, merge the original source digest and the new init digest
  # into one unified digest.
  yield InjectedInitDigest(directory_digest=new_init_files_digest)


def rules():
  return [
      inject_init,
    ]
