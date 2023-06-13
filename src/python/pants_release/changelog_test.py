# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest
from pants_release.changelog import determine_release_branch


@pytest.mark.parametrize(
    ("version", "branch"),
    [
        ("2.0.0.dev0", "main"),
        ("2.0.0.dev1", "main"),
        ("2.0.0a0", "main"),
        ("2.0.0a1", "2.0.x"),
        ("2.0.0rc0", "2.0.x"),
        ("2.0.0rc1", "2.0.x"),
        ("2.0.0", "2.0.x"),
        ("2.0.1a0", "2.0.x"),
        ("2.1234.5678.dev0", "main"),
        ("2.1234.5678.a0", "2.1234.x"),
        ("2.1234.5678.a1", "2.1234.x"),
        ("2.1234.5678rc0", "2.1234.x"),
        ("2.1234.5678", "2.1234.x"),
    ],
)
def test_determine_release_branch(version: str, branch: str) -> None:
    assert determine_release_branch(version) == branch
