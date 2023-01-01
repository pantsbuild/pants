# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple

import pytest

from pants.engine.fs import PathGlobs, Snapshot
from pants.source.filespec import FilespecMatcher
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner()


def assert_rule_match(
    rule_runner: RuleRunner, glob: str, paths: Tuple[str, ...], *, should_match: bool
) -> None:
    # Confirm in-memory behavior.
    matched_filespec = tuple(FilespecMatcher([glob], ()).matches(paths))
    if should_match:
        assert matched_filespec == paths
    else:
        assert not matched_filespec

    # Confirm on-disk behavior.
    for expected_match in paths:
        if expected_match.endswith("/"):
            rule_runner.create_dir(expected_match)
        else:
            rule_runner.write_files({expected_match: ""})
    snapshot = rule_runner.request(Snapshot, [PathGlobs([glob])])
    if should_match:
        assert sorted(paths) == sorted(snapshot.files)
    else:
        assert not snapshot.files


@pytest.mark.parametrize(
    "glob,paths",
    [
        # Single stars.
        ("a/b/*/f.py", ("a/b/c/f.py", "a/b/q/f.py")),
        ("foo/bar/*", ("foo/bar/baz", "foo/bar/bar")),
        ("*/bar/b*", ("foo/bar/baz", "foo/bar/bar")),
        ("*/[be]*/b*", ("foo/bar/baz", "foo/bar/bar")),
        ("foo*/bar", ("foofighters/bar", "foofighters.venv/bar")),
        # Double stars.
        ("**", ("a/b/c", "b")),
        ("a/**/f", ("a/f", "a/b/c/d/e/f")),
        ("a/b/**", ("a/b/d", "a/b/c/d/e/f")),
        # Dots.
        (".*", (".dots", ".dips")),
        ("./*.py", ("f.py", "g.py")),
        # Dirs.
        ("my_dir/", ("my_dir",)),
        ("build-support/*.venv/", ("build-support/blah.venv", "build-support/rbt.venv")),
        # Literals.
        ("a", ("a",)),
        ("a/b/c", ("a/b/c",)),
        ("a/b/c.py", ("a/b/c.py",)),
    ],
)
def test_valid_matches(rule_runner: RuleRunner, glob: str, paths: Tuple[str, ...]) -> None:
    assert_rule_match(rule_runner, glob, paths, should_match=True)


@pytest.mark.parametrize(
    "glob,paths",
    [
        # Single stars.
        ("a/b/*/f.py", ("a/b/c/d/f.py", "a/b/f.py")),
        ("*/bar/b*", ("foo/koo/bar/baz", "foo/bar/bar/zoo")),
        ("foo*/bar", ("foofighters/baz/bar",)),
        # Double stars.
        ("a/b/**", ("a/b",)),
        # Dots.
        (
            ".*",
            (
                "b",
                "a/non/dot/dir/file.py",
                "dist",
                "all/nested/.dot",
                ".some/hidden/nested/dir/file.py",
            ),
        ),
        # Dirs.
        ("dist/", ("not_dist", "cdist", "dist.py", "dist/dist")),
        ("build-support/*.venv/", ("build-support/rbt.venv.but_actually_a_file",)),
        # Case sensitivity
        ("A", ("a",)),
        ("a", ("A",)),
        ("**/BUILD", ("src/rust/build.rs",)),
    ],
)
def test_invalid_matches(rule_runner: RuleRunner, glob: str, paths: Tuple[str, ...]) -> None:
    assert_rule_match(rule_runner, glob, paths, should_match=False)
