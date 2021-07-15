# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from packaging.version import Version

from pants.util import docutil
from pants.util.docutil import doc_url, git_url


def test_doc_url(monkeypatch) -> None:
    monkeypatch.setattr(docutil, "MAJOR_MINOR", "1.29")
    assert doc_url("some-slug") == "https://www.pantsbuild.org/v1.29/docs/some-slug"


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
