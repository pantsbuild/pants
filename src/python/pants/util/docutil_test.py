# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest
from packaging.version import Version

from pants.util import docutil
from pants.util.docutil import doc_url, git_url


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        # versioned
        ("docs/some/path", "https://www.pantsbuild.org/1.29/docs/some/path"),
        ("reference/some/path", "https://www.pantsbuild.org/1.29/reference/some/path"),
        # various things that aren't versioned
        ("docs-extra/some/path", "https://www.pantsbuild.org/docs-extra/some/path"),
        ("reference-extra/some/path", "https://www.pantsbuild.org/reference-extra/some/path"),
        ("some/path", "https://www.pantsbuild.org/some/path"),
        ("community/some/path", "https://www.pantsbuild.org/community/some/path"),
        # a path that already includes the version preserves that version (although we may want to
        # change the behaviour)
        ("2.13/docs/some/path", "https://www.pantsbuild.org/2.13/docs/some/path"),
    ],
)
def test_doc_url_when_versioned(monkeypatch, path: str, expected: str) -> None:
    monkeypatch.setattr(docutil, "MAJOR_MINOR", "1.29")
    assert doc_url(path) == expected


def test_git_url(monkeypatch) -> None:
    monkeypatch.setattr(docutil, "PANTS_SEMVER", Version("1.29.0.dev0"))
    assert (
        git_url("some_file.ext")
        == "https://github.com/pantsbuild/pants/blob/release_1.29.0.dev0/some_file.ext"
    )

    monkeypatch.setattr(docutil, "PANTS_SEMVER", Version("1.29.0rc0"))
    assert (
        git_url("some_file.ext")
        == "https://github.com/pantsbuild/pants/blob/release_1.29.0rc0/some_file.ext"
    )

    monkeypatch.setattr(docutil, "PANTS_SEMVER", Version("1.29.0"))
    assert (
        git_url("some_file.ext")
        == "https://github.com/pantsbuild/pants/blob/release_1.29.0/some_file.ext"
    )
