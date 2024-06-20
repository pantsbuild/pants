# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os

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

    m1 = get_metadata("foo")
    b1 = _path_metadata_to_bytes(m1)
    assert len(b1) > 0

    m2 = get_metadata("sub-dir")
    b2 = _path_metadata_to_bytes(m2)
    assert len(b2) > 0

    m3 = get_metadata("bar")
    b3 = _path_metadata_to_bytes(m3)
    assert len(b3) > 0

    m4 = get_metadata("missing")
    b4 = _path_metadata_to_bytes(m4)
    assert len(b4) == 0
