# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath

import pytest

from pants.source.source_root import NoSourceRootError, SourceRootPatternMatcher


def test_source_root_at_buildroot() -> None:
    srpm = SourceRootPatternMatcher(("/",))
    assert PurePath(".") == srpm.find_root("foo/bar.py")
    assert PurePath(".") == srpm.find_root("foo/")
    assert PurePath(".") == srpm.find_root("foo")
    with pytest.raises(NoSourceRootError):
        srpm.find_root("../foo/bar.py")


def test_fixed_source_roots() -> None:
    srpm = SourceRootPatternMatcher(("/root1", "/foo/root2", "/root1/root3"))
    assert PurePath("root1") == srpm.find_root("root1/bar.py")
    assert PurePath("foo/root2") == srpm.find_root("foo/root2/bar/baz.py")
    assert PurePath("root1/root3") == srpm.find_root("root1/root3/qux.py")
    assert PurePath("root1/root3") == srpm.find_root("root1/root3/qux/quux.py")
    assert PurePath("root1/root3") == srpm.find_root("root1/root3")
    assert srpm.find_root("blah/blah.py") is None


def test_source_root_suffixes() -> None:
    srpm = SourceRootPatternMatcher(("src/python", "/"))
    assert PurePath("src/python") == srpm.find_root("src/python/foo/bar.py")
    assert PurePath("src/python/foo/src/python") == srpm.find_root(
        "src/python/foo/src/python/bar.py"
    )
    assert PurePath(".") == srpm.find_root("foo/bar.py")


def test_source_root_patterns() -> None:
    srpm = SourceRootPatternMatcher(("src/*", "/project/*"))
    assert PurePath("src/python") == srpm.find_root("src/python/foo/bar.py")
    assert PurePath("src/python/foo/src/shell") == srpm.find_root("src/python/foo/src/shell/bar.sh")
    assert PurePath("project/python") == srpm.find_root("project/python/foo/bar.py")
    assert srpm.find_root("prefix/project/python/foo/bar.py") is None
