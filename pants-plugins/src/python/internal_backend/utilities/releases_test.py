# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest
from packaging.version import InvalidVersion, Version

from internal_backend.utilities.register import PantsReleases


def _branch_name(revision_str: str) -> str:
    return PantsReleases._branch_name(Version(revision_str))


def test_branch_name_master() -> None:
    assert "1.1.x" == _branch_name("1.1.0-dev1")
    assert "1.1.x" == _branch_name("1.1.0dev1")
    assert "1.1.x" == _branch_name("1.1.0.dev1")


def test_branch_name_stable() -> None:
    assert "1.1.x" == _branch_name("1.1.0-rc1")
    assert "1.1.x" == _branch_name("1.1.0rc1")
    assert "2.1.x" == _branch_name("2.1.0")
    assert "1.2.x" == _branch_name("1.2.0rc0-12345")

    # A negative example: do not prepend `<number>.`, because # the first two numbers will be taken
    # as branch name.
    assert "12345.1.x" == _branch_name("12345.1.2.0rc0")


def test_invalid_test_branch_name_stable_append_alphabet():
    with pytest.raises(InvalidVersion):
        _branch_name("1.2.0rc0-abcd")


def test_invalid_test_branch_name_stable_prepend_numbers():
    with pytest.raises(InvalidVersion):
        _branch_name("12345-1.2.0rc0")


def test_branch_name_unknown_suffix():
    with pytest.raises(ValueError):
        _branch_name("1.1.0-anything1")
