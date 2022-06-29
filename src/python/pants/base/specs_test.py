# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.base.specs import (
    AddressLiteralSpec,
    AncestorGlobSpec,
    DirGlobSpec,
    DirLiteralSpec,
    RawSpecsWithoutFileOwners,
    RecursiveGlobSpec,
)
from pants.util.frozendict import FrozenDict


@pytest.mark.parametrize(
    "spec,expected",
    [
        (AddressLiteralSpec("dir"), "dir"),
        (AddressLiteralSpec("dir/f.txt"), "dir/f.txt"),
        (AddressLiteralSpec("dir", "tgt"), "dir:tgt"),
        (AddressLiteralSpec("dir", None, "gen"), "dir#gen"),
        (AddressLiteralSpec("dir", "tgt", "gen"), "dir:tgt#gen"),
        (
            AddressLiteralSpec("dir", None, None, FrozenDict({"k1": "v1", "k2": "v2"})),
            "dir@k1=v1,k2=v1",
        ),
        (AddressLiteralSpec("dir", "tgt", None, FrozenDict({"k": "v"})), "dir:tgt@k=v"),
        (AddressLiteralSpec("dir", "tgt", "gen", FrozenDict({"k": "v"})), "dir:tgt#gen@k=v"),
    ],
)
def address_literal_str(spec: AddressLiteralSpec, expected: str) -> None:
    assert str(spec) == expected


def assert_build_file_globs(
    specs: RawSpecsWithoutFileOwners,
    *,
    expected_build_globs: set[str],
    expected_validation_globs: set[str],
) -> None:
    build_path_globs, validation_path_globs = specs.to_build_file_path_globs_tuple(
        build_patterns=["BUILD"], build_ignore_patterns=[]
    )
    assert set(build_path_globs.globs) == expected_build_globs
    assert set(validation_path_globs.globs) == expected_validation_globs


def test_dir_literal() -> None:
    spec = DirLiteralSpec("dir/subdir")
    assert spec.to_glob() == "dir/subdir/*"
    assert spec.matches_target_residence_dir("") is False
    assert spec.matches_target_residence_dir("dir") is False
    assert spec.matches_target_residence_dir("dir/subdir") is True
    assert spec.matches_target_residence_dir("dir/subdir/nested") is False
    assert spec.matches_target_residence_dir("another/subdir") is False
    assert_build_file_globs(
        RawSpecsWithoutFileOwners(dir_literals=(spec,), description_of_origin="tests"),
        expected_build_globs={"BUILD", "dir/BUILD", "dir/subdir/BUILD"},
        expected_validation_globs={"dir/subdir/*"},
    )

    spec = DirLiteralSpec("")
    assert spec.to_glob() == "*"
    assert spec.matches_target_residence_dir("") is True
    assert spec.matches_target_residence_dir("dir") is False
    assert_build_file_globs(
        RawSpecsWithoutFileOwners(dir_literals=(spec,), description_of_origin="tests"),
        expected_build_globs={"BUILD"},
        expected_validation_globs={"*"},
    )


def test_dir_glob() -> None:
    spec = DirGlobSpec("dir/subdir")
    assert spec.to_glob() == "dir/subdir/*"
    assert spec.matches_target_residence_dir("") is False
    assert spec.matches_target_residence_dir("dir") is False
    assert spec.matches_target_residence_dir("dir/subdir") is True
    assert spec.matches_target_residence_dir("dir/subdir/nested") is False
    assert spec.matches_target_residence_dir("another/subdir") is False
    assert_build_file_globs(
        RawSpecsWithoutFileOwners(dir_globs=(spec,), description_of_origin="tests"),
        expected_build_globs={"BUILD", "dir/BUILD", "dir/subdir/BUILD"},
        expected_validation_globs={"dir/subdir/*"},
    )

    spec = DirGlobSpec("")
    assert spec.to_glob() == "*"
    assert spec.matches_target_residence_dir("") is True
    assert spec.matches_target_residence_dir("dir") is False
    assert_build_file_globs(
        RawSpecsWithoutFileOwners(dir_globs=(spec,), description_of_origin="tests"),
        expected_build_globs={"BUILD"},
        expected_validation_globs={"*"},
    )


def test_recursive_glob() -> None:
    spec = RecursiveGlobSpec("dir/subdir")
    assert spec.to_glob() == "dir/subdir/**"
    assert spec.matches_target_residence_dir("") is False
    assert spec.matches_target_residence_dir("dir") is False
    assert spec.matches_target_residence_dir("dir/subdir") is True
    assert spec.matches_target_residence_dir("dir/subdir/nested") is True
    assert spec.matches_target_residence_dir("dir/subdir/nested/again") is True
    assert spec.matches_target_residence_dir("another/subdir") is False
    assert_build_file_globs(
        RawSpecsWithoutFileOwners(recursive_globs=(spec,), description_of_origin="tests"),
        expected_build_globs={"BUILD", "dir/BUILD", "dir/subdir/BUILD", "dir/subdir/**/BUILD"},
        expected_validation_globs={"dir/subdir/**"},
    )

    spec = RecursiveGlobSpec("")
    assert spec.to_glob() == "**"
    assert spec.matches_target_residence_dir("") is True
    assert spec.matches_target_residence_dir("dir") is True
    assert spec.matches_target_residence_dir("another_dir") is True
    assert_build_file_globs(
        RawSpecsWithoutFileOwners(recursive_globs=(spec,), description_of_origin="tests"),
        expected_build_globs={"BUILD", "**/BUILD"},
        expected_validation_globs={"**"},
    )


def test_ancestor_glob() -> None:
    spec = AncestorGlobSpec("dir/subdir")
    assert spec.matches_target_residence_dir("") is True
    assert spec.matches_target_residence_dir("dir") is True
    assert spec.matches_target_residence_dir("dir/subdir") is True
    assert spec.matches_target_residence_dir("dir/subdir/nested") is False
    assert spec.matches_target_residence_dir("another/subdir") is False
    assert_build_file_globs(
        RawSpecsWithoutFileOwners(ancestor_globs=(spec,), description_of_origin="tests"),
        expected_build_globs={"BUILD", "dir/BUILD", "dir/subdir/BUILD"},
        expected_validation_globs={"dir/subdir/*"},
    )

    spec = AncestorGlobSpec("")
    assert spec.matches_target_residence_dir("") is True
    assert spec.matches_target_residence_dir("dir") is False
    assert_build_file_globs(
        RawSpecsWithoutFileOwners(ancestor_globs=(spec,), description_of_origin="tests"),
        expected_build_globs={"BUILD"},
        expected_validation_globs={"*"},
    )
