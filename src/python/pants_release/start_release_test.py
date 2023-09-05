# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest
from packaging.version import Version
from pants_release.start_release import ReleaseInfo


@pytest.mark.parametrize(
    ("raw_version", "slug", "branch"),
    [
        ("2.0.0.dev0", "2.0.x", "main"),
        ("2.0.0.dev1", "2.0.x", "main"),
        ("2.0.0a0", "2.0.x", "main"),
        ("2.0.0a1", "2.0.x", "2.0.x"),
        ("2.0.0rc0", "2.0.x", "2.0.x"),
        ("2.0.0rc1", "2.0.x", "2.0.x"),
        ("2.0.0", "2.0.x", "2.0.x"),
        ("2.0.1a0", "2.0.x", "2.0.x"),
        ("2.1234.5678.dev0", "2.1234.x", "main"),
        ("2.1234.5678.a0", "2.1234.x", "2.1234.x"),
        ("2.1234.5678.a1", "2.1234.x", "2.1234.x"),
        ("2.1234.5678rc0", "2.1234.x", "2.1234.x"),
        ("2.1234.5678", "2.1234.x", "2.1234.x"),
    ],
)
def test_releaseinfo_determine(raw_version: str, slug: str, branch: str) -> None:
    version = Version(raw_version)
    expected = ReleaseInfo(version=version, slug=slug, branch=branch)

    computed = ReleaseInfo.determine(version)
    assert computed == expected
