# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.base.specs import (
    AncestorGlobSpec,
    DirGlobSpec,
    RecursiveGlobSpec,
    SpecsWithoutFileOwners,
)


def assert_build_file_globs(specs: SpecsWithoutFileOwners, expected: set[str]) -> None:
    result = specs.to_build_file_path_globs(build_patterns=["BUILD"], build_ignore_patterns=[])
    assert set(result.globs) == expected


def test_dir_glob() -> None:
    spec = DirGlobSpec("dir/subdir")
    assert spec.matches_target("") is False
    assert spec.matches_target("dir") is False
    assert spec.matches_target("dir/subdir") is True
    assert spec.matches_target("dir/subdir/nested") is False
    assert spec.matches_target("another/subdir") is False
    assert_build_file_globs(
        SpecsWithoutFileOwners(dir_globs=(spec,)), {"BUILD", "dir/BUILD", "dir/subdir/BUILD"}
    )

    spec = DirGlobSpec("")
    assert spec.matches_target("") is True
    assert spec.matches_target("dir") is False
    assert_build_file_globs(SpecsWithoutFileOwners(dir_globs=(spec,)), {"BUILD"})


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
        {"BUILD", "dir/BUILD", "dir/subdir/BUILD", "dir/subdir/**/BUILD"},
    )

    spec = RecursiveGlobSpec("")
    assert spec.matches_target("") is True
    assert spec.matches_target("dir") is True
    assert spec.matches_target("another_dir") is True
    assert_build_file_globs(SpecsWithoutFileOwners(recursive_globs=(spec,)), {"BUILD", "**/BUILD"})


def test_ancestor_glob() -> None:
    spec = AncestorGlobSpec("dir/subdir")
    assert spec.matches_target("") is True
    assert spec.matches_target("dir") is True
    assert spec.matches_target("dir/subdir") is True
    assert spec.matches_target("dir/subdir/nested") is False
    assert spec.matches_target("another/subdir") is False
    assert_build_file_globs(
        SpecsWithoutFileOwners(ancestor_globs=(spec,)), {"BUILD", "dir/BUILD", "dir/subdir/BUILD"}
    )

    spec = AncestorGlobSpec("")
    assert spec.matches_target("") is True
    assert spec.matches_target("dir") is False
    assert_build_file_globs(SpecsWithoutFileOwners(ancestor_globs=(spec,)), {"BUILD"})
