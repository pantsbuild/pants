# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
from typing import Any, Mapping

import pytest

from pants.backend.visibility.glob import PathGlob, TargetGlob
from pants.engine.addresses import Address
from pants.engine.internals.target_adaptor import TargetAdaptor


@pytest.mark.parametrize(
    "pattern, base, anchor_mode, raw, glob, text",
    [
        ("foo", "base", "", "foo", "foo$", "foo"),
        (".", "base", ".", "", "$", "."),
        ("./foo", "base", ".", "foo", "foo$", "./foo"),
        ("/foo", "base", "/", "base/foo", "base/foo$", "base/foo"),
        ("//foo", "base", "//", "foo", "foo$", "//foo"),
        ("foo/**/bar", "base", "", "foo/**/bar", "foo(/.*)?/bar$", "foo/**/bar"),
        ("foo/../bar", "base", "", "bar", "bar$", "bar"),
    ],
)
def test_pathglob_parse(
    pattern: str, base: str, anchor_mode: str, raw: str, glob: str, text: str
) -> None:
    parsed = PathGlob.parse(pattern, base)
    assert raw == parsed.raw
    assert anchor_mode == parsed.anchor_mode.value
    assert glob == parsed.glob.pattern
    assert text == str(parsed)


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
def test_pathglob_match_path(
    glob: PathGlob, tests: tuple[tuple[str, str, str | None], ...]
) -> None:
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
def test_pathglob_match(glob: PathGlob, tests: tuple[tuple[str, str, bool], ...]) -> None:
    for path, base, expected in tests:
        print(path, base)
        assert expected == glob.match(path, base)


@pytest.mark.parametrize(
    "target_spec, expected",
    [
        ({}, "*"),
        ("", "*"),
        (dict(type="resources"), "resources"),
        (dict(type="file", path="glob/*/this.ext"), "file[glob/*/this.ext]"),
        (dict(path="glob/*/this.ext"), "[glob/*/this.ext]"),
        (dict(tags=["tagged"]), "(tagged)"),
        (dict(tags=["tag-a", "tag-b , b", "c"]), "(tag-a, 'tag-b , b', c)"),
        (dict(type="file*", tags=["foo", "bar"], path="baz.txt"), "file*(foo, bar)[baz.txt]"),
        ("resources", "resources"),
        ("file[glob/*/this.ext]", "file[glob/*/this.ext]"),
        ("[glob/*/this.ext]", "[glob/*/this.ext]"),
        ("(tag-a)", "(tag-a)"),
        ("(tag-a  ,  tag-b)", "(tag-a, tag-b)"),
        ("file*(foo, bar)[baz.txt]", "file*(foo, bar)[baz.txt]"),
    ],
)
def test_target_glob_parse_spec(target_spec: str | Mapping[str, Any], expected: str) -> None:
    assert expected == str(TargetGlob.parse(target_spec, "base"))


def tagged(type_alias: str, name: str | None = None, *tags: str, **kwargs) -> TargetAdaptor:
    kwargs["tags"] = tags
    return TargetAdaptor(type_alias, name, **kwargs)


@pytest.mark.parametrize(
    "expected, target_spec",
    [
        (True, "*"),
        (True, "file"),
        (True, "(tag-c)"),
        (True, "(tag-*)"),
        (False, "(tag-b)"),
        (True, "[file.ext]"),
        (False, "[files.ext]"),
        (True, "[//src/*]"),
        (True, "file(tag-a, tag-c)[src/file.ext]"),
        (False, "file(tag-a, tag-b)[src/file.ext]"),
        (False, "resource"),
    ],
)
def test_targetglob_match(expected: bool, target_spec: str) -> None:
    path = "src/file.ext"
    adaptor = TargetAdaptor("file", None, tags=["tag-a", "tag-c"])
    address = Address(os.path.dirname(path), relative_file_path=os.path.basename(path))
    assert expected == TargetGlob.parse(target_spec, "src").match(address, adaptor, "src")
