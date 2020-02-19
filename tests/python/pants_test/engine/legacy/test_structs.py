# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.engine.fs import PathGlobs
from pants.engine.legacy.structs import Files, Globs
from pants.option.custom_types import GlobExpansionConjunction


def test_filespec_with_explicit_exclude() -> None:
    globs = Globs(spec_path="")
    assert globs.filespecs == {"globs": []}
    globs = Globs(exclude=["*.md"], spec_path="")
    assert globs.filespecs == {"globs": [], "exclude": [{"globs": ["*.md"]}]}


def test_explicit_exclude_of_wrong_type() -> None:
    with pytest.raises(ValueError) as excinfo:
        Globs(exclude="*.md", spec_path="")  # type: ignore[arg-type]
    assert str(excinfo.value) == "Excludes should be a list of strings. Got: '*.md'"


def test_ignore_globs_parsed_correctly() -> None:
    files = Files("foo.py", "!ignore.py", "!**/*", spec_path="")
    assert files.to_path_globs(
        relpath="src/python", conjunction=GlobExpansionConjunction.any_match,
    ) == PathGlobs(["src/python/foo.py", "!src/python/ignore.py", "!src/python/**/*"])
    # Check that we maintain backwards compatibility with the `filespecs` property used by V1.
    assert files.filespecs == {"globs": ["foo.py"], "exclude": [{"globs": ["ignore.py", "**/*"]}]}
