# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.jvm.resolve.coursier_fetch import CoursierResolvedLockfile
from pants.jvm.resolve.lockfile_metadata import JVMLockfileMetadata


def _make_empty_lockfile() -> bytes:
    lockfile = CoursierResolvedLockfile(entries=())
    metadata = JVMLockfileMetadata.new([])
    return metadata.add_header_to_lockfile(
        lockfile.to_serialized(),
        regenerate_command="N/A - empty lockfile for test",
        delimeter="#",
    )


EMPTY_JVM_LOCKFILE = _make_empty_lockfile()
