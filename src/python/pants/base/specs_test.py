# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.base.specs import (
    AncestorGlobSpec,
    DirGlobSpec,
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


def test_dir_glob() -> None:
    spec = DirGlobSpec("dir/subdir")
    assert spec.matches_target("") is False
    assert spec.matches_target("dir") is False
    assert spec.matches_target("dir/subdir") is True
    assert spec.matches_target("dir/subdir/nested") is False
    assert spec.matches_target("another/subdir") is False
    assert_build_file_globs(
        SpecsWithoutFileOwners(dir_globs=(spec,)),
        expected_build_globs={"BUILD", "dir/BUILD", "dir/subdir/BUILD"},
        expected_validation_globs={"dir/subdir/*"},
    )

    spec = DirGlobSpec("")
    assert spec.matches_target("") is True
    assert spec.matches_target("dir") is False
    assert_build_file_globs(
        SpecsWithoutFileOwners(dir_globs=(spec,)),
        expected_build_globs={"BUILD"},
        expected_validation_globs={"*"},
    )


def test_recursive_glob() -> None:
    spec = RecursiveGlobSpec("dir/subdir")
    assert spec.matches_target("") is False
    assert spec.matches_target("dir") is False
    assert spec.matches_target("dir/subdir") is True
    assert spec.matches_target("dir/subdir/nested") is True
    assert spec.matches_target("dir/subdir/nested/again") is True
    assert spec.matches_target("another/subdir") is False
    assert_build_file_globs(
        SpecsWithoutFileOwners(recursive_globs=(spec,)),
        expected_build_globs={"BUILD", "dir/BUILD", "dir/subdir/BUILD", "dir/subdir/**/BUILD"},
        expected_validation_globs={"dir/subdir/**"},
    )

    spec = RecursiveGlobSpec("")
    assert spec.matches_target("") is True
    assert spec.matches_target("dir") is True
    assert spec.matches_target("another_dir") is True
    assert_build_file_globs(
        SpecsWithoutFileOwners(recursive_globs=(spec,)),
        expected_build_globs={"BUILD", "**/BUILD"},
        expected_validation_globs={"**"},
    )


def test_ancestor_glob() -> None:
    spec = AncestorGlobSpec("dir/subdir")
    assert spec.matches_target("") is True
    assert spec.matches_target("dir") is True
    assert spec.matches_target("dir/subdir") is True
    assert spec.matches_target("dir/subdir/nested") is False
    assert spec.matches_target("another/subdir") is False
    assert_build_file_globs(
        SpecsWithoutFileOwners(ancestor_globs=(spec,)),
        expected_build_globs={"BUILD", "dir/BUILD", "dir/subdir/BUILD"},
        expected_validation_globs={"dir/subdir/*"},
    )

    spec = AncestorGlobSpec("")
    assert spec.matches_target("") is True
    assert spec.matches_target("dir") is False
    assert_build_file_globs(
        SpecsWithoutFileOwners(ancestor_globs=(spec,)),
        expected_build_globs={"BUILD"},
        expected_validation_globs={"*"},
    )
