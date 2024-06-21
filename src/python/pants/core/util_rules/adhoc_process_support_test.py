# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from datetime import timedelta
import os
from pathlib import Path

import pytest

from pants.core.util_rules.adhoc_process_support import _path_metadata_to_bytes
from pants.engine.fs import PathMetadataRequest, PathMetadataResult
from pants.engine.internals.native_engine import PathMetadata
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            QueryRule(PathMetadataResult, (PathMetadataRequest,)),
        ],
        isolated_local_store=True,
    )


def test_path_metadata_to_bytes(rule_runner: RuleRunner) -> None:
    def get_metadata(path: str) -> PathMetadata | None:
        result = rule_runner.request(PathMetadataResult, [PathMetadataRequest(path)])
        return result.metadata

    rule_runner.write_files(
        {
            "foo": b"xyzzy",
            "sub-dir/bar": b"12345",
        }
    )
    os.symlink("foo", os.path.join(rule_runner.build_root, "bar"))

    m_file = get_metadata("foo")
    assert m_file is not None
    b_file = _path_metadata_to_bytes(m_file)
    assert len(b_file) > 0

    m_dir = get_metadata("sub-dir")
    assert m_dir is not None
    b_dir = _path_metadata_to_bytes(m_dir)
    assert len(b_dir) > 0

    m_symlink = get_metadata("bar")
    assert m_symlink is not None
    b_symlink = _path_metadata_to_bytes(m_symlink)
    assert len(b_symlink) > 0

    m_missing = get_metadata("missing")
    assert m_missing is None
    b_missing = _path_metadata_to_bytes(m_missing)
    assert len(b_missing) == 0

    # Update the access time only and see if conversion remains the same.
    m = m_file.copy()
    atime = m.accessed
    assert atime is not None
    m.accessed = atime + timedelta(seconds=1)
    b1 = _path_metadata_to_bytes(m)
    assert len(b1) > 0
    assert b_file == b1

    # Update the modified time and conversion should differ.
    mtime = m.modified
    assert mtime is not None
    m.modified = mtime + timedelta(seconds=1)
    b2 = _path_metadata_to_bytes(m)
    assert len(b2) > 0
    assert b1 != b2
