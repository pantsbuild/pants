# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import pytest

from pants.backend.visibility.glob import PathGlob


@pytest.mark.parametrize(
    "pattern, base, anchor_mode, glob",
    [
        ("foo", "base", "", "foo$"),
        (".", "base", ".", "$"),
        ("./foo", "base", ".", "foo$"),
        ("/foo", "base", "/", "base/foo$"),
        ("//foo", "base", "//", "foo$"),
    ],
)
def test_parse_pattern(pattern: str, base: str, anchor_mode: str, glob: str) -> None:
    parsed = PathGlob.parse(pattern, base)
    assert pattern == parsed.raw
    assert anchor_mode == parsed.anchor_mode.value
    assert glob == parsed.glob.pattern


@pytest.mark.parametrize(
    "glob, tests",
    [
        (
            PathGlob.parse("./foo/bar", "base"),
            (
                ("tests/foo", "src", None),
                ("src/foo", "src", "foo"),
                ("src/foo", "src/a", None),
            ),
        ),
    ],
)
def test_match_path(glob: PathGlob, tests: tuple[tuple[str, str, str | None], ...]) -> None:
    for path, base, expected in tests:
        assert expected == glob._match_path(path, base)


@pytest.mark.parametrize(
    "glob, tests",
    [
        (
            PathGlob.parse("//foo/bar", "base"),
            (
                ("tests/foo", "src", False),
                ("src/foo", "src", False),
                ("foo/bar", "src/a", True),
                ("foo/bar/baz", "src/a", False),
            ),
        ),
        (
            PathGlob.parse("/foo/bar", "base"),
            (
                ("foo/bar", "src", False),
                ("base/foo/bar", "src", True),
                ("src/foo/bar", "src", False),
            ),
        ),
        (
            PathGlob.parse("./foo/bar", "base"),
            (
                ("foo/bar", "src", False),
                ("base/foo/bar", "src", False),
                ("src/foo/bar", "src", True),
            ),
        ),
        (
            PathGlob.parse(".", "base"),
            (
                ("foo/bar", "src", False),
                ("base/foo/bar", "src", False),
                ("src/foo/bar", "src", False),
                ("src/proj", "src/proj", True),
            ),
        ),
        (
            PathGlob.parse("./foo", "base"),
            (
                ("foo/bar", "src", False),
                ("base/foo/bar", "src", False),
                ("src/foo/bar", "src", False),
                ("src/foo", "src", True),
            ),
        ),
        (
            PathGlob.parse("foo/bar", "base"),
            (
                ("foo/bar", "src", True),
                ("base/foo/bar", "src", True),
                ("src/foo/bar", "src", True),
                ("foo/bar/baz", "src", False),
            ),
        ),
    ],
)
def test_match(glob: PathGlob, tests: tuple[tuple[str, str, bool], ...]) -> None:
    for path, base, expected in tests:
        print(path, base)
        assert expected == glob.match(path, base)
