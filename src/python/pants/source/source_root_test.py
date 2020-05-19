# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.source.source_root import NoSourceRootError, SourceRoot, SourceRoots, SourceRootTrie
from pants.testutil.test_base import TestBase


def test_source_root_at_buildroot() -> None:
    srs = SourceRoots(["/"])
    assert SourceRoot(".") == srs.strict_find_by_path("foo/bar.py")
    assert SourceRoot(".") == srs.strict_find_by_path("foo/")
    assert SourceRoot(".") == srs.strict_find_by_path("foo")
    with pytest.raises(NoSourceRootError):
        srs.strict_find_by_path("../foo/bar.py")


def test_fixed_source_roots() -> None:
    srs = SourceRoots(["/root1", "/foo/root2", "/root1/root3"])
    assert SourceRoot("root1") == srs.strict_find_by_path("root1/bar.py")
    assert SourceRoot("foo/root2") == srs.strict_find_by_path("foo/root2/bar/baz.py")
    assert SourceRoot("root1/root3") == srs.strict_find_by_path("root1/root3/qux.py")
    assert SourceRoot("root1/root3") == srs.strict_find_by_path("root1/root3/qux/quux.py")
    assert SourceRoot("root1/root3") == srs.strict_find_by_path("root1/root3")
    with pytest.raises(NoSourceRootError):
        srs.strict_find_by_path("blah/blah.py")


def test_source_root_suffixes() -> None:
    srs = SourceRoots(["src/python", "/"])
    assert SourceRoot("src/python") == srs.strict_find_by_path("src/python/foo/bar.py")
    assert SourceRoot("src/python/foo/src/python") == srs.strict_find_by_path(
        "src/python/foo/src/python/bar.py"
    )
    assert SourceRoot(".") == srs.strict_find_by_path("foo/bar.py")


def test_source_root_patterns() -> None:
    srs = SourceRoots(["src/*", "/project/*"])
    assert SourceRoot("src/python") == srs.strict_find_by_path("src/python/foo/bar.py")
    assert SourceRoot("src/python/foo/src/shell") == srs.strict_find_by_path(
        "src/python/foo/src/shell/bar.sh"
    )
    assert SourceRoot("project/python") == srs.strict_find_by_path("project/python/foo/bar.py")
    with pytest.raises(NoSourceRootError):
        srs.strict_find_by_path("prefix/project/python/foo/bar.py")


class SourceRootTest(TestBase):
    # TODO: Delete all the *_deprecated tests below in 1.30.0.dev0.
    def test_source_root_trie_deprecated(self):
        trie = SourceRootTrie()
        self.assertIsNone(trie.find("src/java/org/pantsbuild/foo/Foo.java"))

        def root(path):
            return SourceRoot(path)

        # Wildcard at the end.
        trie.add_pattern("src/*")
        self.assertEqual(root("src/java"), trie.find("src/java/org/pantsbuild/foo/Foo.java"))
        self.assertEqual(
            root("my/project/src/java"),
            trie.find("my/project/src/java/org/pantsbuild/foo/Foo.java"),
        )
        self.assertEqual(root("src/python"), trie.find("src/python/pantsbuild/foo/foo.py"))
        self.assertEqual(
            root("my/project/src/python"),
            trie.find("my/project/src/python/org/pantsbuild/foo/foo.py"),
        )

        # Overlapping pattern.
        trie.add_pattern("src/main/*")
        self.assertEqual(
            root("src/main/java"), trie.find("src/main/java/org/pantsbuild/foo/Foo.java")
        )
        self.assertEqual(
            root("my/project/src/main/java"),
            trie.find("my/project/src/main/java/org/pantsbuild/foo/Foo.java"),
        )
        self.assertEqual(
            root("src/main/python"), trie.find("src/main/python/pantsbuild/foo/foo.py")
        )
        self.assertEqual(
            root("my/project/src/main/python"),
            trie.find("my/project/src/main/python/org/pantsbuild/foo/foo.py"),
        )

        # Wildcard in the middle.
        trie.add_pattern("src/*/code")
        self.assertEqual(
            root("src/java/code"), trie.find("src/java/code/org/pantsbuild/foo/Foo.java")
        )
        self.assertEqual(
            root("my/project/src/java/code"),
            trie.find("my/project/src/java/code/org/pantsbuild/foo/Foo.java"),
        )
        self.assertEqual(
            root("src/python/code"), trie.find("src/python/code/pantsbuild/foo/foo.py")
        )
        self.assertEqual(
            root("my/project/src/python/code"),
            trie.find("my/project/src/python/code/org/pantsbuild/foo/foo.py"),
        )

        # Verify that the now even-more-overlapping pattern still works.
        self.assertEqual(
            root("src/main/java"), trie.find("src/main/java/org/pantsbuild/foo/Foo.java")
        )
        self.assertEqual(
            root("my/project/src/main/java"),
            trie.find("my/project/src/main/java/org/pantsbuild/foo/Foo.java"),
        )
        self.assertEqual(
            root("src/main/python"), trie.find("src/main/python/pantsbuild/foo/foo.py")
        )
        self.assertEqual(
            root("my/project/src/main/python"),
            trie.find("my/project/src/main/python/org/pantsbuild/foo/foo.py"),
        )

        # Verify that we take the first matching prefix.
        self.assertEqual(root("src/java"), trie.find("src/java/src/python/Foo.java"))

        # Test canonicalization.
        self.assertEqual(root("src/jvm"), trie.find("src/jvm/org/pantsbuild/foo/Foo.java"))
        self.assertEqual(root("src/jvm"), trie.find("src/jvm/org/pantsbuild/foo/Foo.scala"))
        self.assertEqual(root("src/py"), trie.find("src/py/pantsbuild/foo/foo.py"))

        # Non-canonicalized language names should also be detected.
        self.assertEqual(root("src/kotlin"), trie.find("src/kotlin/org/pantsbuild/foo/Foo.kotlin"))

        # Test fixed roots.
        trie.add_fixed("mysrc/scalastuff")
        self.assertEqual(
            SourceRoot("mysrc/scalastuff"),
            trie.find("mysrc/scalastuff/org/pantsbuild/foo/Foo.scala"),
        )
        self.assertIsNone(trie.find("my/project/mysrc/scalastuff/org/pantsbuild/foo/Foo.scala"))

        # Verify that a fixed root wins over a pattern that is a prefix of it
        # (e.g., that src/go/src wins over src/go).
        trie.add_fixed("src/go/src")
        self.assertEqual(root("src/go/src"), trie.find("src/go/src/foo/bar/baz.go"))

        # Verify that the repo root can be a fixed source root.
        trie.add_fixed("")
        self.assertEqual(root(""), trie.find("foo/bar/baz.py"))

    def test_source_root_trie_traverse_deprecated(self):
        def make_trie() -> SourceRootTrie:
            return SourceRootTrie()

        trie = make_trie()
        self.assertEqual(set(), trie.traverse())

        trie.add_pattern("src/*")
        trie.add_pattern("src/main/*")
        self.assertEqual({"src/*", "src/main/*"}, trie.traverse())

        trie = make_trie()
        trie.add_pattern("*")
        trie.add_pattern("src/*/code")
        trie.add_pattern("src/main/*/code")
        trie.add_pattern("src/main/*")
        trie.add_pattern("src/main/*/foo")
        self.assertEqual(
            {"*", "src/*/code", "src/main/*/code", "src/main/*", "src/main/*", "src/main/*/foo"},
            trie.traverse(),
        )

        trie = make_trie()
        trie.add_fixed("src/scala-source-code")
        trie.add_pattern("src/*/code")
        trie.add_pattern("src/main/*/code")
        self.assertEqual(
            {"src/*/code", "^/src/scala-source-code", "src/main/*/code"}, trie.traverse()
        )

    def test_fixed_source_root_at_buildroot_deprecated(self):
        trie = SourceRootTrie()
        trie.add_fixed("",)

        self.assertEqual(SourceRoot(""), trie.find("foo/proto/bar/baz.proto"))

    def test_source_root_pattern_at_buildroot_deprecated(self):
        trie = SourceRootTrie()
        trie.add_pattern("*")

        self.assertEqual(SourceRoot("java"), trie.find("java/bar/baz.proto"))

    def test_invalid_patterns_deprecated(self):
        trie = SourceRootTrie()
        # Bad normalization.
        self.assertRaises(SourceRootTrie.InvalidPath, lambda: trie.add_fixed("foo/bar/"))
        self.assertRaises(SourceRootTrie.InvalidPath, lambda: trie.add_pattern("foo//*"))
        self.assertRaises(SourceRootTrie.InvalidPath, lambda: trie.add_pattern("foo/*/"))

        # Asterisk in fixed pattern.
        self.assertRaises(SourceRootTrie.InvalidPath, lambda: trie.add_fixed("src/*"))

    def test_trie_traversal_deprecated(self):
        trie = SourceRootTrie()
        trie.add_pattern("foo1/bar1/baz1")
        trie.add_pattern("foo1/bar1/baz2/qux")
        trie.add_pattern("foo1/bar2/baz1")
        trie.add_pattern("foo1/bar2/baz2")
        trie.add_pattern("foo2/bar1")
        trie.add_fixed("fixed1/bar1")
        trie.add_fixed("fixed2/bar2")

        # Test raw traversal.
        self.assertEqual(
            {"baz1", "baz2/qux"}, set(trie._root.children["foo1"].children["bar1"].subpatterns()),
        )

        self.assertEqual(
            {"bar1/baz1", "bar1/baz2/qux", "bar2/baz1", "bar2/baz2",},
            set(trie._root.children["foo1"].subpatterns()),
        )

        self.assertEqual(
            {
                "foo1/bar1/baz1",
                "foo1/bar1/baz2/qux",
                "foo1/bar2/baz1",
                "foo1/bar2/baz2",
                "foo2/bar1",
                "^/fixed1/bar1",
                "^/fixed2/bar2",
            },
            set(trie._root.subpatterns()),
        )

        # Test the fixed() method.
        self.assertEqual(
            {"fixed1/bar1", "fixed2/bar2"}, set(trie.fixed()),
        )
