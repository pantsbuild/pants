# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.source.source_root import (SourceRoot, SourceRootCategories, SourceRootConfig,
                                      SourceRootFactory, SourceRootTrie)
from pants_test.base_test import BaseTest


# Shorthand, to cut some verbosity down in the tests.
UNKNOWN = SourceRootCategories.UNKNOWN
SOURCE = SourceRootCategories.SOURCE
TEST = SourceRootCategories.TEST
THIRDPARTY = SourceRootCategories.THIRDPARTY


class SourceRootTest(BaseTest):
  def test_source_root_trie(self):
    trie = SourceRootTrie(SourceRootFactory({
      'jvm': ('java', 'scala'),
      'py': ('python',)
    }))
    self.assertIsNone(trie.find('src/java/org/pantsbuild/foo/Foo.java'))

    def root(path, langs):
      return SourceRoot(path, langs, UNKNOWN)

    # Wildcard at the end.
    trie.add_pattern('src/*')
    self.assertEquals(root('src/java', ('java',)),
                      trie.find('src/java/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(root('my/project/src/java', ('java',)),
                      trie.find('my/project/src/java/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(root('src/python', ('python',)),
                      trie.find('src/python/pantsbuild/foo/foo.py'))
    self.assertEquals(root('my/project/src/python', ('python',)),
                      trie.find('my/project/src/python/org/pantsbuild/foo/foo.py'))

    # Overlapping pattern.
    trie.add_pattern('src/main/*')
    self.assertEquals(root('src/main/java', ('java',)),
                      trie.find('src/main/java/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(root('my/project/src/main/java', ('java',)),
                      trie.find('my/project/src/main/java/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(root('src/main/python', ('python',)),
                      trie.find('src/main/python/pantsbuild/foo/foo.py'))
    self.assertEquals(root('my/project/src/main/python', ('python',)),
                      trie.find('my/project/src/main/python/org/pantsbuild/foo/foo.py'))

    # Wildcard in the middle.
    trie.add_pattern('src/*/code')
    self.assertEquals(root('src/java/code', ('java',)),
                      trie.find('src/java/code/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(root('my/project/src/java/code', ('java',)),
                      trie.find('my/project/src/java/code/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(root('src/python/code', ('python',)),
                      trie.find('src/python/code/pantsbuild/foo/foo.py'))
    self.assertEquals(root('my/project/src/python/code', ('python',)),
                      trie.find('my/project/src/python/code/org/pantsbuild/foo/foo.py'))

    # Verify that the now even-more-overlapping pattern still works.
    self.assertEquals(root('src/main/java', ('java',)),
                      trie.find('src/main/java/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(root('my/project/src/main/java', ('java',)),
                      trie.find('my/project/src/main/java/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(root('src/main/python', ('python',)),
                      trie.find('src/main/python/pantsbuild/foo/foo.py'))
    self.assertEquals(root('my/project/src/main/python', ('python',)),
                      trie.find('my/project/src/main/python/org/pantsbuild/foo/foo.py'))

    # Verify that we take the first matching prefix.
    self.assertEquals(root('src/java', ('java',)),
                      trie.find('src/java/src/python/Foo.java'))

    # Test canonicalization.
    self.assertEquals(root('src/jvm', ('java', 'scala')),
                      trie.find('src/jvm/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(root('src/jvm', ('java', 'scala')),
                      trie.find('src/jvm/org/pantsbuild/foo/Foo.scala'))
    self.assertEquals(root('src/py', ('python',)),
                      trie.find('src/py/pantsbuild/foo/foo.py'))

    # Test fixed roots.
    trie.add_fixed('mysrc/scalastuff', ('scala',))
    self.assertEquals(('mysrc/scalastuff', ('scala',), UNKNOWN),
                      trie.find('mysrc/scalastuff/org/pantsbuild/foo/Foo.scala'))
    self.assertIsNone(trie.find('my/project/mysrc/scalastuff/org/pantsbuild/foo/Foo.scala'))

    # Verify that a fixed root wins over a pattern that is a prefix of it
    # (e.g., that src/go/src wins over src/go).
    trie.add_fixed('src/go/src', ('go',))
    self.assertEquals(root('src/go/src', ('go',)),
                      trie.find('src/go/src/foo/bar/baz.go'))

  def test_fixed_source_root_at_buildroot(self):
    trie = SourceRootTrie(SourceRootFactory({}))
    trie.add_fixed('', ('proto',))

    self.assertEquals(('', ('proto',), UNKNOWN),
                      trie.find('foo/proto/bar/baz.proto'))

  def test_source_root_pattern_at_buildroot(self):
    trie = SourceRootTrie(SourceRootFactory({}))
    trie.add_pattern('*')

    self.assertEquals(('java', ('java',), UNKNOWN),
                      trie.find('java/bar/baz.proto'))

  def test_invalid_patterns(self):
    trie = SourceRootTrie(SourceRootFactory({}))
    # Bad normalization.
    self.assertRaises(SourceRootTrie.InvalidPath, lambda: trie.add_fixed('foo/bar/', ('bar',)))
    self.assertRaises(SourceRootTrie.InvalidPath, lambda: trie.add_pattern('foo//*', ('java',)))
    self.assertRaises(SourceRootTrie.InvalidPath, lambda: trie.add_pattern('foo/*/', ('java',)))

    # Asterisk in fixed pattern.
    self.assertRaises(SourceRootTrie.InvalidPath, lambda: trie.add_fixed('src/*', ('java',)))

  def test_trie_traversal(self):
    trie = SourceRootTrie(SourceRootFactory({}))
    trie.add_pattern('foo1/bar1/baz1')
    trie.add_pattern('foo1/bar1/baz2/qux')
    trie.add_pattern('foo1/bar2/baz1')
    trie.add_pattern('foo1/bar2/baz2')
    trie.add_pattern('foo2/bar1')
    trie.add_fixed('fixed1/bar1', ['lang1'], SOURCE)
    trie.add_fixed('fixed2/bar2', ['lang2'], TEST)

    # Test raw traversal.
    self.assertEquals([('baz1', (), UNKNOWN),
                       ('baz2/qux', (), UNKNOWN)],
                      list(trie._root.children['foo1'].children['bar1'].subpatterns()))

    self.assertEquals([('bar1/baz1', (), UNKNOWN),
                       ('bar1/baz2/qux', (), UNKNOWN),
                       ('bar2/baz1', (), UNKNOWN),
                       ('bar2/baz2', (), UNKNOWN)],
                      list(trie._root.children['foo1'].subpatterns()))

    self.assertEquals([('foo1/bar1/baz1', (), UNKNOWN),
                       ('foo1/bar1/baz2/qux', (), UNKNOWN),
                       ('foo1/bar2/baz1', (), UNKNOWN),
                       ('foo1/bar2/baz2', (), UNKNOWN),
                       ('foo2/bar1', (), UNKNOWN),
                       ('^/fixed1/bar1', ('lang1',), SOURCE),
                       ('^/fixed2/bar2', ('lang2',), TEST)],
                      list(trie._root.subpatterns()))

    # Test the fixed() method.
    self.assertEquals([('fixed1/bar1', ('lang1',), SOURCE),
                       ('fixed2/bar2', ('lang2',), TEST)],
                      trie.fixed())

  def test_all_roots(self):
    self.create_dir('contrib/go/examples/3rdparty/go')
    self.create_dir('contrib/go/examples/src/go/src')
    self.create_dir('src/java')
    self.create_dir('src/python')
    self.create_dir('src/example/java')
    self.create_dir('src/example/python')
    self.create_dir('my/project/src/java')
    self.create_dir('fixed/root/jvm')
    self.create_dir('not/a/srcroot/java')

    options = {
      'build_file_rev': None,
      'pants_ignore': [],

      'source_root_patterns': ['src/*', 'src/example/*'],
      'source_roots': {
        # Fixed roots should trump patterns which would detect contrib/go/examples/src/go here.
        'contrib/go/examples/src/go/src': ['go'],

        # Dir does not exist, should not be listed as a root.
        'java': ['java']}
    }
    options.update(self.options[''])  # We need inherited values for pants_workdir etc.

    self.context(for_subsystems=[SourceRootConfig], options={
      SourceRootConfig.options_scope: options
    })
    source_roots = SourceRootConfig.global_instance().get_source_roots()
    # Ensure that we see any manually added roots.
    source_roots.add_source_root('fixed/root/jvm', ('java', 'scala'), TEST)
    source_roots.all_roots()

    self.assertEquals({SourceRoot('contrib/go/examples/3rdparty/go', ('go',), THIRDPARTY),
                       SourceRoot('contrib/go/examples/src/go/src', ('go',), SOURCE),
                       SourceRoot('src/java', ('java',), SOURCE),
                       SourceRoot('src/python', ('python',), SOURCE),
                       SourceRoot('src/example/java', ('java',), SOURCE),
                       SourceRoot('src/example/python', ('python',), SOURCE),
                       SourceRoot('my/project/src/java', ('java',), SOURCE),
                       SourceRoot('fixed/root/jvm', ('java','scala'), TEST)},
                      set(source_roots.all_roots()))
