# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.base.specs import AscendantAddresses, DescendantAddresses, SiblingAddresses


def test_sibling_addresses() -> None:
    spec = SiblingAddresses("dir/subdir")
    assert spec.to_build_file_globs(["BUILD"]) == {"dir/subdir/BUILD"}
    assert spec.matches("") is False
    assert spec.matches("dir") is False
    assert spec.matches("dir/subdir") is True
    assert spec.matches("dir/subdir/nested") is False
    assert spec.matches("another/subdir") is False

    spec = SiblingAddresses("")
    assert spec.to_build_file_globs(["BUILD"]) == {"BUILD"}
    assert spec.matches("") is True
    assert spec.matches("dir") is False


def test_descendant_addresses() -> None:
    spec = DescendantAddresses("dir/subdir")
    assert spec.to_build_file_globs(["BUILD"]) == {"dir/subdir/**/BUILD"}
    assert spec.matches("") is False
    assert spec.matches("dir") is False
    assert spec.matches("dir/subdir") is True
    assert spec.matches("dir/subdir/nested") is True
    assert spec.matches("dir/subdir/nested/again") is True
    assert spec.matches("another/subdir") is False

    spec = DescendantAddresses("")
    assert spec.to_build_file_globs(["BUILD"]) == {"**/BUILD"}
    assert spec.matches("") is True
    assert spec.matches("dir") is True
    assert spec.matches("another_dir") is True


def test_ascendant_addresses() -> None:
    spec = AscendantAddresses("dir/subdir")
    assert spec.to_build_file_globs(["BUILD"]) == {"BUILD", "dir/BUILD", "dir/subdir/BUILD"}
    assert spec.matches("") is True
    assert spec.matches("dir") is True
    assert spec.matches("dir/subdir") is True
    assert spec.matches("dir/subdir/nested") is False
    assert spec.matches("another/subdir") is False

    spec = AscendantAddresses("")
    assert spec.to_build_file_globs(["BUILD"]) == {"BUILD"}
    assert spec.matches("") is True
    assert spec.matches("dir") is False
