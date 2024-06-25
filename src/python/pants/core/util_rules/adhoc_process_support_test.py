# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pants.core.util_rules.adhoc_process_support import _path_metadata_to_bytes
from pants.engine.internals.native_engine import PathMetadata, PathMetadataKind


def test_path_metadata_to_bytes() -> None:
    now = datetime.now(timezone.utc)

    m_file = PathMetadata(
        path="foo",
        kind=PathMetadataKind.FILE,
        length=5,
        is_executable=False,
        unix_mode=0o666,
        accessed=now,
        created=now,
        modified=now,
        symlink_target=None,
    )
    b_file = _path_metadata_to_bytes(m_file)
    assert len(b_file) > 0

    m_dir = PathMetadata(
        path="sub-dir",
        kind=PathMetadataKind.DIRECTORY,
        length=5,
        is_executable=False,
        unix_mode=0o777,
        accessed=now,
        created=now,
        modified=now,
        symlink_target=None,
    )
    assert m_dir is not None
    b_dir = _path_metadata_to_bytes(m_dir)
    assert len(b_dir) > 0

    m_symlink = PathMetadata(
        path="bar",
        kind=PathMetadataKind.SYMLINK,
        length=5,
        is_executable=False,
        unix_mode=0o555,
        accessed=now,
        created=now,
        modified=now,
        symlink_target="foo",
    )
    assert m_symlink is not None
    b_symlink = _path_metadata_to_bytes(m_symlink)
    assert len(b_symlink) > 0

    b_missing = _path_metadata_to_bytes(None)
    assert len(b_missing) == 0

    # Update the access time only and see if conversion remains the same.
    atime = m_file.accessed
    assert atime is not None
    m1 = PathMetadata(
        path=m_file.path,
        kind=m_file.kind,
        length=m_file.length,
        is_executable=m_file.is_executable,
        unix_mode=m_file.unix_mode,
        accessed=atime + timedelta(seconds=1),
        created=m_file.created,
        modified=m_file.modified,
        symlink_target=m_file.symlink_target,
    )
    b1 = _path_metadata_to_bytes(m1)
    assert len(b1) > 0
    assert b_file == b1

    # Update the modified time and conversion should differ.
    mtime = m1.modified
    assert mtime is not None
    m2 = PathMetadata(
        path=m1.path,
        kind=m1.kind,
        length=m1.length,
        is_executable=m1.is_executable,
        unix_mode=m1.unix_mode,
        accessed=m1.accessed,
        created=m1.created,
        modified=mtime + timedelta(seconds=1),
        symlink_target=m1.symlink_target,
    )
    b2 = _path_metadata_to_bytes(m2)
    assert len(b2) > 0
    assert b1 != b2
