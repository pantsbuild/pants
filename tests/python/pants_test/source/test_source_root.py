# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.source.source_root import SourceRoot, SourceRootConfig, SourceRootTrie
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import create_subsystem


class SourceRootTest(BaseTest):
  def test_source_root_trie(self):
    trie = SourceRootTrie({
      'jvm': ('java', 'scala'),
      'py': ('python',)
    })
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

  def test_all_roots(self):
    self.create_dir('contrib/go/examples/3rdparty/go')
    self.create_dir('contrib/go/examples/src/go')
    self.create_dir('src/java')
    self.create_dir('src/python')
    self.create_dir('src/example/java')
    self.create_dir('src/example/python')
    self.create_dir('my/project/src/java')
    self.create_dir('not/a/srcroot/java')

    options = {
      'source_root_patterns': ['src/*', 'src/example/*'],
      # Test that our 'go_remote' hack works.
      # TODO: This will be redundant once we have proper "3rdparty"/"remote" support.
      'source_roots': { 'contrib/go/examples/3rdparty/go': ['go_remote'] }
    }
    options.update(self.options[''])  # We need inherited values for pants_workdir etc.

    source_roots = create_subsystem(SourceRootConfig, **options).get_source_roots()
    self.assertEquals({SourceRoot('contrib/go/examples/3rdparty/go', ('go_remote',)),
                       SourceRoot('contrib/go/examples/src/go', ('go',)),
                       SourceRoot('src/java', ('java',)),
                       SourceRoot('src/python', ('python',)),
                       SourceRoot('src/example/java', ('java',)),
                       SourceRoot('src/example/python', ('python',)),
                       SourceRoot('my/project/src/java', ('java',))},
                      set(source_roots.all_roots()))
