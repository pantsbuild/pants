# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.source.source_root import SourceRoot, SourceRootConfig, SourceRootTrie
from pants.testutil.test_base import TestBase


class SourceRootTest(TestBase):
    def test_source_root_trie(self):
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

    def test_source_root_trie_traverse(self):
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

    def test_fixed_source_root_at_buildroot(self):
        trie = SourceRootTrie()
        trie.add_fixed("",)

        self.assertEqual(SourceRoot(""), trie.find("foo/proto/bar/baz.proto"))

    def test_source_root_pattern_at_buildroot(self):
        trie = SourceRootTrie()
        trie.add_pattern("*")

        self.assertEqual(SourceRoot("java"), trie.find("java/bar/baz.proto"))

    def test_invalid_patterns(self):
        trie = SourceRootTrie()
        # Bad normalization.
        self.assertRaises(SourceRootTrie.InvalidPath, lambda: trie.add_fixed("foo/bar/"))
        self.assertRaises(SourceRootTrie.InvalidPath, lambda: trie.add_pattern("foo//*"))
        self.assertRaises(SourceRootTrie.InvalidPath, lambda: trie.add_pattern("foo/*/"))

        # Asterisk in fixed pattern.
        self.assertRaises(SourceRootTrie.InvalidPath, lambda: trie.add_fixed("src/*"))

    def test_trie_traversal(self):
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

    def test_all_roots(self):
        self.create_dir("contrib/go/examples/3rdparty/go")
        self.create_dir("contrib/go/examples/src/go/src")
        self.create_dir("src/java")
        self.create_dir("src/python")
        self.create_dir("src/kotlin")
        self.create_dir("src/example/java")
        self.create_dir("src/example/python")
        self.create_dir("my/project/src/java")
        self.create_dir("fixed/root/jvm")
        self.create_dir("not/a/srcroot/java")

        options = {
            "pants_ignore": [],
            "source_root_patterns": ["src/*", "src/example/*"],
            "source_roots": {
                # Fixed roots should trump patterns which would detect contrib/go/examples/src/go here.
                "contrib/go/examples/src/go/src": ["go"],
                # Dir does not exist, should not be listed as a root.
                "java": ["java"],
            },
        }
        options.update(self.options[""])  # We need inherited values for pants_workdir etc.

        self.context(
            for_subsystems=[SourceRootConfig], options={SourceRootConfig.options_scope: options}
        )
        source_roots = SourceRootConfig.global_instance().get_source_roots()
        # Ensure that we see any manually added roots.
        source_roots.add_source_root("fixed/root/jvm")
        source_roots.all_roots()

        self.assertEqual(
            {
                SourceRoot("contrib/go/examples/3rdparty/go"),
                SourceRoot("contrib/go/examples/src/go/src"),
                SourceRoot("src/java"),
                SourceRoot("src/python"),
                SourceRoot("src/kotlin"),
                SourceRoot("src/example/java"),
                SourceRoot("src/example/python"),
                SourceRoot("my/project/src/java"),
                SourceRoot("fixed/root/jvm"),
            },
            set(source_roots.all_roots()),
        )
