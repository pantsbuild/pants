# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.base.specs import (
    AncestorGlobSpec,
    DirGlobSpec,
    DirLiteralSpec,
    RecursiveGlobSpec,
    SpecsWithoutFileOwners,
)


def assert_build_file_globs(
    specs: SpecsWithoutFileOwners,
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
        SpecsWithoutFileOwners(dir_literals=(spec,)),
        expected_build_globs={"BUILD", "dir/BUILD", "dir/subdir/BUILD"},
        expected_validation_globs={"dir/subdir/*"},
    )

    spec = DirLiteralSpec("")
    assert spec.to_glob() == "*"
    assert spec.matches_target_residence_dir("") is True
    assert spec.matches_target_residence_dir("dir") is False
    assert_build_file_globs(
        SpecsWithoutFileOwners(dir_literals=(spec,)),
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
        SpecsWithoutFileOwners(dir_globs=(spec,)),
        expected_build_globs={"BUILD", "dir/BUILD", "dir/subdir/BUILD"},
        expected_validation_globs={"dir/subdir/*"},
    )

    spec = DirGlobSpec("")
    assert spec.to_glob() == "*"
    assert spec.matches_target_residence_dir("") is True
    assert spec.matches_target_residence_dir("dir") is False
    assert_build_file_globs(
        SpecsWithoutFileOwners(dir_globs=(spec,)),
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
        SpecsWithoutFileOwners(recursive_globs=(spec,)),
        expected_build_globs={"BUILD", "dir/BUILD", "dir/subdir/BUILD", "dir/subdir/**/BUILD"},
        expected_validation_globs={"dir/subdir/**"},
    )

    spec = RecursiveGlobSpec("")
    assert spec.to_glob() == "**"
    assert spec.matches_target_residence_dir("") is True
    assert spec.matches_target_residence_dir("dir") is True
    assert spec.matches_target_residence_dir("another_dir") is True
    assert_build_file_globs(
        SpecsWithoutFileOwners(recursive_globs=(spec,)),
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
        SpecsWithoutFileOwners(ancestor_globs=(spec,)),
        expected_build_globs={"BUILD", "dir/BUILD", "dir/subdir/BUILD"},
        expected_validation_globs={"dir/subdir/*"},
    )

    spec = AncestorGlobSpec("")
    assert spec.matches_target_residence_dir("") is True
    assert spec.matches_target_residence_dir("dir") is False
    assert_build_file_globs(
        SpecsWithoutFileOwners(ancestor_globs=(spec,)),
        expected_build_globs={"BUILD"},
        expected_validation_globs={"*"},
    )
