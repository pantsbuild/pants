# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
import re
from typing import Any, Mapping

import pytest

from pants.backend.visibility.glob import PathGlob, PathGlobAnchorMode, TargetGlob
from pants.engine.addresses import Address
from pants.engine.internals.target_adaptor import TargetAdaptor


@pytest.mark.parametrize(
    "base, pattern_text, expected",
    [
        (
            "base",
            "foo",
            PathGlob(
                raw="foo",
                anchor_mode=PathGlobAnchorMode.FLOATING,
                glob=re.compile(r"/?\bfoo$"),
                uplvl=0,
            ),
        ),
        (
            "base",
            ".",
            PathGlob(
                raw="", anchor_mode=PathGlobAnchorMode.INVOKED_PATH, glob=re.compile("$"), uplvl=0
            ),
        ),
        (
            "base",
            "./foo",
            PathGlob(
                raw="foo",
                anchor_mode=PathGlobAnchorMode.INVOKED_PATH,
                glob=re.compile("foo$"),
                uplvl=0,
            ),
        ),
        (
            "base",
            ("../foo/../bar", "../bar"),
            PathGlob(
                raw="bar",
                anchor_mode=PathGlobAnchorMode.INVOKED_PATH,
                glob=re.compile("bar$"),
                uplvl=1,
            ),
        ),
        (
            "base",
            ("/foo", "base/foo"),
            PathGlob(
                raw="base/foo",
                anchor_mode=PathGlobAnchorMode.DECLARED_PATH,
                glob=re.compile("base/foo$"),
                uplvl=0,
            ),
        ),
        (
            "base/sub",
            ("/../bar", "base/bar"),
            PathGlob(
                raw="base/bar",
                anchor_mode=PathGlobAnchorMode.DECLARED_PATH,
                glob=re.compile("base/bar$"),
                uplvl=0,
            ),
        ),
        (
            "base",
            ("/foo/../baz", "base/baz"),
            PathGlob(
                raw="base/baz",
                anchor_mode=PathGlobAnchorMode.DECLARED_PATH,
                glob=re.compile("base/baz$"),
                uplvl=0,
            ),
        ),
        (
            "base",
            "//foo",
            PathGlob(
                raw="foo",
                anchor_mode=PathGlobAnchorMode.PROJECT_ROOT,
                glob=re.compile(r"foo$"),
                uplvl=0,
            ),
        ),
        (
            "base",
            "foo/**/bar",
            PathGlob(
                raw="foo/**/bar",
                anchor_mode=PathGlobAnchorMode.FLOATING,
                glob=re.compile(r"/?\bfoo(/.*)?/bar$"),
                uplvl=0,
            ),
        ),
        (
            "base",
            ("foo/../bar", "bar"),
            PathGlob(
                raw="bar",
                anchor_mode=PathGlobAnchorMode.FLOATING,
                glob=re.compile(r"/?\bbar$"),
                uplvl=0,
            ),
        ),
        (
            "base",
            "my_file.ext",
            PathGlob(
                raw="my_file.ext",
                anchor_mode=PathGlobAnchorMode.FLOATING,
                glob=re.compile(r"/?\bmy_file\.ext$"),
                uplvl=0,
            ),
        ),
        (
            "base",
            "*my_file.ext",
            PathGlob(
                raw="*my_file.ext",
                anchor_mode=PathGlobAnchorMode.FLOATING,
                glob=re.compile(r"[^/]*my_file\.ext$"),
                uplvl=0,
            ),
        ),
        (
            "base",
            ".ext",
            PathGlob(
                raw=".ext",
                anchor_mode=PathGlobAnchorMode.FLOATING,
                glob=re.compile(r"\.ext$"),
                uplvl=0,
            ),
        ),
        (
            "base",
            "**/path",
            PathGlob(
                raw="**/path",
                anchor_mode=PathGlobAnchorMode.FLOATING,
                glob=re.compile(r"/?\bpath$"),
                uplvl=0,
            ),
        ),
    ],
)
def test_pathglob_parse(base: str, pattern_text: str | tuple[str, str], expected: PathGlob) -> None:
    if isinstance(pattern_text, tuple):
        pattern, text = pattern_text
    else:
        pattern, text = (pattern_text,) * 2
    actual = PathGlob.parse(pattern, base)
    assert expected.anchor_mode == actual.anchor_mode
    assert expected.glob.pattern == actual.glob.pattern
    assert text == str(actual)
    assert expected == actual


@pytest.mark.parametrize(
    "glob, tests",
    [
        (
            PathGlob.parse("./foo/bar", "base"),
            (
                # path, base, expected
                ("tests/foo", "src", None),
                ("src/foo", "src", "foo"),
                ("src/foo", "src/a", None),
            ),
        ),
        (
            PathGlob.parse("../foo/bar", "base"),
            (
                # path, base, expected
                ("src/foo/bar", "src/qux", "foo/bar"),
                ("", "snout", ""),
                ("", "snout/deep", None),
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
        assert expected == glob.match(path, base)


@pytest.mark.parametrize(
    "target_spec, expected",
    [
        ({"path": ""}, "!*"),
        ("[]", "!*"),
        (dict(type="resources"), "<resources>"),
        (dict(type="file", path="glob/*/this.ext"), "<file>[glob/*/this.ext]"),
        (dict(path="glob/*/this.ext"), "glob/*/this.ext"),
        (dict(tags=["tagged"]), "(tagged)"),
        (dict(tags=["tag-a", "tag-b , b", "c"]), "(tag-a, 'tag-b , b', c)"),
        (dict(type="file*", tags=["foo", "bar"], path="baz.txt"), "<file*>[baz.txt](foo, bar)"),
        ("<resources>", "<resources>"),
        ("<file>[glob/*/this.ext]", "<file>[glob/*/this.ext]"),
        ("glob/*/this.ext", "glob/*/this.ext"),
        ("(tag-a)", "(tag-a)"),
        ("(tag-a  ,  tag-b)", "(tag-a, tag-b)"),
        ("<file*>(foo, bar)[baz.txt]", "<file*>[baz.txt](foo, bar)"),
        (":name", ":name"),
        (dict(name="name"), ":name"),
        (dict(path="src/*", name="name"), "src/*:name"),
        (dict(type="target", path="src", name="name"), "<target>[src:name]"),
    ],
)
def test_target_glob_parse_spec(target_spec: str | Mapping[str, Any], expected: str) -> None:
    assert expected == str(TargetGlob.parse(target_spec, "base"))


@pytest.mark.parametrize(
    "expected, target_spec",
    [
        (True, "*"),
        (True, "<file>"),
        (True, "(tag-c)"),
        (True, "(tag-*)"),
        (False, "(tag-b)"),
        (True, "[file.ext]"),
        (False, "[files.ext]"),
        (True, "//src/*"),
        (True, "<file>(tag-a, tag-c)[src/file.ext]"),
        (False, "<file>(tag-a, tag-b)[src/file.ext]"),
        (False, "<resource>"),
        (False, ":name"),
        (True, ":src"),
        (True, ":*"),
        (False, "other.txt:src"),
        (True, "file.ext:src"),
        (True, "src/file.ext:src"),
    ],
)
def test_targetglob_match(expected: bool, target_spec: str) -> None:
    path = "src/file.ext"
    adaptor = TargetAdaptor(
        "file", None, tags=["tag-a", "tag-c"], __description_of_origin__="BUILD:1"
    )
    address = Address(os.path.dirname(path), relative_file_path=os.path.basename(path))
    assert expected == TargetGlob.parse(target_spec, "src").match(address, adaptor, "src")


@pytest.mark.parametrize(
    "address, path",
    [
        (Address("src", relative_file_path="file"), "src/file"),
        (Address("src", target_name="name"), "src"),
        (Address("src", target_name="gen", generated_name="name"), "src/gen#name"),
        (Address("", relative_file_path="file"), "file"),
        (Address("", target_name="name"), ""),
        (Address("", target_name="gen", generated_name="name"), "gen#name"),
    ],
)
def test_address_path(address: Address, path: str) -> None:
    assert TargetGlob.address_path(address) == path
