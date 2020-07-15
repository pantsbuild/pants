# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple

from pants.engine.fs import PathGlobs, Snapshot
from pants.source.filespec import matches_filespec
from pants.testutil.test_base import TestBase


class FilespecTest(TestBase):
    def assert_rule_match(
        self, glob: str, paths: Tuple[str, ...], *, should_match: bool = True
    ) -> None:
        # Confirm in-memory behavior.
        matched_filespec = matches_filespec({"includes": [glob]}, paths=paths)
        if should_match:
            assert matched_filespec == paths
        else:
            assert not matched_filespec

        # Confirm on-disk behavior.
        for expected_match in paths:
            if expected_match.endswith("/"):
                self.create_dir(expected_match)
            else:
                self.create_file(expected_match)
        snapshot = self.request_single_product(Snapshot, PathGlobs([glob]))
        if should_match:
            assert sorted(paths) == sorted(snapshot.files)
        else:
            assert not snapshot.files

    def test_matches_single_star_0(self) -> None:
        self.assert_rule_match("a/b/*/f.py", ("a/b/c/f.py", "a/b/q/f.py"))

    def test_matches_single_star_0_neg(self) -> None:
        self.assert_rule_match("a/b/*/f.py", ("a/b/c/d/f.py", "a/b/f.py"), should_match=False)

    def test_matches_single_star_1(self) -> None:
        self.assert_rule_match("foo/bar/*", ("foo/bar/baz", "foo/bar/bar"))

    def test_matches_single_star_2(self) -> None:
        self.assert_rule_match("*/bar/b*", ("foo/bar/baz", "foo/bar/bar"))

    def test_matches_single_star_2_neg(self) -> None:
        self.assert_rule_match(
            "*/bar/b*", ("foo/koo/bar/baz", "foo/bar/bar/zoo"), should_match=False
        )

    def test_matches_single_star_3(self) -> None:
        self.assert_rule_match("*/[be]*/b*", ("foo/bar/baz", "foo/bar/bar"))

    def test_matches_single_star_4(self) -> None:
        self.assert_rule_match("foo*/bar", ("foofighters/bar", "foofighters.venv/bar"))

    def test_matches_single_star_4_neg(self) -> None:
        self.assert_rule_match("foo*/bar", ("foofighters/baz/bar",), should_match=False)

    def test_matches_double_star_0(self) -> None:
        self.assert_rule_match("**", ("a/b/c", "b"))

    def test_matches_double_star_1(self) -> None:
        self.assert_rule_match("a/**/f", ("a/f", "a/b/c/d/e/f"))

    def test_matches_double_star_2(self) -> None:
        self.assert_rule_match("a/b/**", ("a/b/d", "a/b/c/d/e/f"))

    def test_matches_double_star_2_neg(self) -> None:
        self.assert_rule_match("a/b/**", ("a/b",), should_match=False)

    def test_matches_dots(self) -> None:
        self.assert_rule_match(".*", (".dots", ".dips"))

    def test_matches_dots_relative(self) -> None:
        self.assert_rule_match("./*.py", ("f.py", "g.py"))

    def test_matches_dots_neg(self) -> None:
        self.assert_rule_match(
            ".*",
            (
                "b",
                "a/non/dot/dir/file.py",
                "dist",
                "all/nested/.dot",
                ".some/hidden/nested/dir/file.py",
            ),
            should_match=False,
        )

    def test_matches_dirs(self) -> None:
        self.assert_rule_match("dist/", ("dist",))

    def test_matches_dirs_neg(self) -> None:
        self.assert_rule_match(
            "dist/", ("not_dist", "cdist", "dist.py", "dist/dist"), should_match=False
        )

    def test_matches_dirs_dots(self) -> None:
        self.assert_rule_match(
            "build-support/*.venv/", ("build-support/blah.venv", "build-support/rbt.venv")
        )

    def test_matches_dirs_dots_neg(self) -> None:
        self.assert_rule_match(
            "build-support/*.venv/",
            ("build-support/rbt.venv.but_actually_a_file",),
            should_match=False,
        )

    def test_matches_literals(self) -> None:
        self.assert_rule_match("a", ("a",))

    def test_matches_literal_dir(self) -> None:
        self.assert_rule_match("a/b/c", ("a/b/c",))

    def test_matches_literal_file(self) -> None:
        self.assert_rule_match("a/b/c.py", ("a/b/c.py",))
