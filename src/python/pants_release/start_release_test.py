# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import datetime

import pytest
from packaging.version import Version
from pants_release.start_release import Category, Entry, ReleaseInfo, format_notes, splice


@pytest.mark.parametrize(
    ("raw_version", "slug", "branch"),
    [
        ("2.0.0.dev0", "2.0.x", "main"),
        ("2.0.0.dev1", "2.0.x", "main"),
        ("2.0.0a0", "2.0.x", "main"),
        ("2.0.0a1", "2.0.x", "2.0.x"),
        ("2.0.0rc0", "2.0.x", "2.0.x"),
        ("2.0.0rc1", "2.0.x", "2.0.x"),
        ("2.0.0", "2.0.x", "2.0.x"),
        ("2.0.1a0", "2.0.x", "2.0.x"),
        ("2.1234.5678.dev0", "2.1234.x", "main"),
        ("2.1234.5678.a0", "2.1234.x", "2.1234.x"),
        ("2.1234.5678.a1", "2.1234.x", "2.1234.x"),
        ("2.1234.5678rc0", "2.1234.x", "2.1234.x"),
        ("2.1234.5678", "2.1234.x", "2.1234.x"),
    ],
)
def test_releaseinfo_determine(raw_version: str, slug: str, branch: str) -> None:
    version = Version(raw_version)
    expected = ReleaseInfo(version=version, slug=slug, branch=branch)

    computed = ReleaseInfo.determine(version)
    assert computed == expected


@pytest.mark.parametrize("category", [*(c for c in Category if c is not Category.Internal), None])
def test_format_notes_external(category: None | Category) -> None:
    release_info = ReleaseInfo(version=Version("2.1234.0.dev0"), slug="2.1234.x", branch="main")
    entries = [Entry(category=category, text="some entry")]
    date = datetime.date(9999, 8, 7)
    heading = "Uncategorized" if category is None else category.heading()

    formatted = format_notes(release_info, entries, date)

    assert formatted.internal == ""
    # we're testing the exact formatting, so no softwrap/dedent:
    assert (
        formatted.external
        == f"""\
## 2.1234.0.dev0 (Aug 07, 9999)

### {heading}

some entry"""
    )


def test_format_notes_internal() -> None:
    release_info = ReleaseInfo(version=Version("2.1234.0.dev0"), slug="2.1234.x", branch="main")
    entries = [Entry(category=Category.Internal, text="some entry")]
    date = datetime.date(9999, 8, 7)

    formatted = format_notes(release_info, entries, date)

    assert formatted.external == "## 2.1234.0.dev0 (Aug 07, 9999)"
    # we're testing the exact formatting, so no softwrap/dedent:
    assert (
        formatted.internal
        == """\
### Internal (put these in a PR comment for review, not the release notes)

some entry"""
    )


@pytest.mark.parametrize(
    ("existing_contents", "expected"),
    [
        pytest.param(
            "# 2.1234.x Release series\n",
            "# 2.1234.x Release series\n\nNEW SECTION\n",
            id="defaults to end of file",
        ),
        pytest.param(
            "# 2.1234.x Release series\n\n## 2.1234.5678rc9\nEXISTING1## 2.1234.0.dev0\nEXISTING2",
            "# 2.1234.x Release series\n\nNEW SECTION\n\n## 2.1234.5678rc9\nEXISTING1## 2.1234.0.dev0\nEXISTING2",
            id="finds the first release-like section",
        ),
        pytest.param(
            "# 2.1234.x Release series\n\n## What's new\n\n---\n\n## 2.1234.5678rc9\nEXISTING1",
            "# 2.1234.x Release series\n\n## What's new\n\n---\n\nNEW SECTION\n\n## 2.1234.5678rc9\nEXISTING1",
            id="ignores 'What's new'",
        ),
        pytest.param(
            "# 2.1234.x Release series\n\n### 2.1234\nEXISTING\n",
            "# 2.1234.x Release series\n\n### 2.1234\nEXISTING\n\nNEW SECTION\n",
            id="ignores unexpected heading depth",
        ),
    ],
)
def test_splice(existing_contents: str, expected: str) -> None:
    assert splice(existing_contents, "NEW SECTION") == expected
