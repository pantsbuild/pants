# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.source.source_root import SourceRoot, SourceRootConfig, SourceRootFactory, SourceRootTrie
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import create_subsystem


class SourceRootTest(BaseTest):
  def test_source_root_trie(self):
    trie = SourceRootTrie(SourceRootFactory({
      'jvm': ('java', 'scala'),
      'py': ('python',)
    }))
    self.assertIsNone(trie.find('src/java/org/pantsbuild/foo/Foo.java'))

    # Wildcard at the end.
    trie.add_pattern('src/*')
    self.assertEquals(SourceRoot('src/java', ('java',)),
                      trie.find('src/java/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(SourceRoot('my/project/src/java', ('java',)),
                      trie.find('my/project/src/java/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(SourceRoot('src/python', ('python',)),
                      trie.find('src/python/pantsbuild/foo/foo.py'))
    self.assertEquals(SourceRoot('my/project/src/python', ('python',)),
                      trie.find('my/project/src/python/org/pantsbuild/foo/foo.py'))

    # Overlapping pattern.
    trie.add_pattern('src/main/*')
    self.assertEquals(SourceRoot('src/main/java', ('java',)),
                      trie.find('src/main/java/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(SourceRoot('my/project/src/main/java', ('java',)),
                      trie.find('my/project/src/main/java/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(SourceRoot('src/main/python', ('python',)),
                      trie.find('src/main/python/pantsbuild/foo/foo.py'))
    self.assertEquals(SourceRoot('my/project/src/main/python', ('python',)),
                      trie.find('my/project/src/main/python/org/pantsbuild/foo/foo.py'))

    # Wildcard in the middle.
    trie.add_pattern('src/*/code')
    self.assertEquals(SourceRoot('src/java/code', ('java',)),
                      trie.find('src/java/code/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(SourceRoot('my/project/src/java/code', ('java',)),
                      trie.find('my/project/src/java/code/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(SourceRoot('src/python/code', ('python',)),
                      trie.find('src/python/code/pantsbuild/foo/foo.py'))
    self.assertEquals(SourceRoot('my/project/src/python/code', ('python',)),
                      trie.find('my/project/src/python/code/org/pantsbuild/foo/foo.py'))

    # Verify that the now even-more-overlapping pattern still works.
    self.assertEquals(SourceRoot('src/main/java', ('java',)),
                      trie.find('src/main/java/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(SourceRoot('my/project/src/main/java', ('java',)),
                      trie.find('my/project/src/main/java/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(SourceRoot('src/main/python', ('python',)),
                      trie.find('src/main/python/pantsbuild/foo/foo.py'))
    self.assertEquals(SourceRoot('my/project/src/main/python', ('python',)),
                      trie.find('my/project/src/main/python/org/pantsbuild/foo/foo.py'))

    # Verify that we take the first matching prefix.
    self.assertEquals(SourceRoot('src/java', ('java',)),
                      trie.find('src/java/src/python/Foo.java'))

    # Test canonicalization.
    self.assertEquals(SourceRoot('src/jvm', ('java', 'scala')),
                      trie.find('src/jvm/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(SourceRoot('src/jvm', ('java', 'scala')),
                      trie.find('src/jvm/org/pantsbuild/foo/Foo.scala'))
    self.assertEquals(SourceRoot('src/py', ('python',)),
                      trie.find('src/py/pantsbuild/foo/foo.py'))

    # Test fixed patterns.
    trie.add_fixed('mysrc/scalastuff', ('scala',))
    self.assertEquals(('mysrc/scalastuff', ('scala',)),
                      trie.find('mysrc/scalastuff/org/pantsbuild/foo/Foo.scala'))
    self.assertIsNone(trie.find('my/project/mysrc/scalastuff/org/pantsbuild/foo/Foo.scala'))

  def test_trie_traversal(self):
    trie = SourceRootTrie(SourceRootFactory({}))
    trie.add_pattern('foo1/bar1/baz1')
    trie.add_pattern('foo1/bar1/baz2/qux')
    trie.add_pattern('foo1/bar2/baz1')
    trie.add_pattern('foo1/bar2/baz2')
    trie.add_pattern('foo2/bar1')
    trie.add_fixed('fixed1/bar1', ['lang1'])
    trie.add_fixed('fixed2/bar2', ['lang2'])

    # Test raw traversal.
    self.assertEquals([('baz1', ()), ('baz2/qux', ())],
                      list(trie._root.children['foo1'].children['bar1'].subpatterns()))

    self.assertEquals([('bar1/baz1', ()), ('bar1/baz2/qux', ()),
                       ('bar2/baz1', ()), ('bar2/baz2', ())],
                      list(trie._root.children['foo1'].subpatterns()))

    self.assertEquals([('foo1/bar1/baz1', ()), ('foo1/bar1/baz2/qux', ()),
                       ('foo1/bar2/baz1', ()), ('foo1/bar2/baz2', ()), ('foo2/bar1', ()),
                       ('^/fixed1/bar1', ('lang1',)), ('^/fixed2/bar2', ('lang2',))],
                      list(trie._root.subpatterns()))

    # Test the fixed() method.
    self.assertEquals([('fixed1/bar1', ('lang1',)), ('fixed2/bar2', ('lang2',))],
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

        # Test that our 'go_remote' hack works.
        # TODO: This will be redundant once we have proper "3rdparty"/"remote" support.
        'contrib/go/examples/3rdparty/go': ['go_remote'],

        # Dir does not exist, should not be listed as a root.
        'java': ['java']}
    }
    options.update(self.options[''])  # We need inherited values for pants_workdir etc.

    source_roots = create_subsystem(SourceRootConfig, **options).get_source_roots()
    # Ensure that we see any manually added roots.
    source_roots.add_source_root('fixed/root/jvm', ('java', 'scala'))
    source_roots.all_roots()

    self.assertEquals({SourceRoot('contrib/go/examples/3rdparty/go', ('go_remote',)),
                       SourceRoot('contrib/go/examples/src/go/src', ('go',)),
                       SourceRoot('src/java', ('java',)),
                       SourceRoot('src/python', ('python',)),
                       SourceRoot('src/example/java', ('java',)),
                       SourceRoot('src/example/python', ('python',)),
                       SourceRoot('my/project/src/java', ('java',)),
                       SourceRoot('fixed/root/jvm', ('java','scala'))},
                      set(source_roots.all_roots()))
