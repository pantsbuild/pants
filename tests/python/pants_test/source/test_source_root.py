# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.source.source_root import SourceRootConfig, SourceRootTrie
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import create_subsystem


class SourceRootTest(BaseTest):
  def test_generate_source_root_patterns(self):
    def _do_test(langs=None,
                 source_root_parents=None, source_roots=None,
                 test_root_parents=None, test_roots=None,
                 expected=None):
      options = {
        'langs': langs or [],
        'source_root_parents': source_root_parents or [],
        'source_root_patterns': source_roots or {},
        'test_root_parents': test_root_parents or [],
        'test_root_patterns': test_roots or {},
      }
      source_root_config = create_subsystem(SourceRootConfig, **options)
      actual = dict(source_root_config.generate_source_root_pattern_mappings())
      self.assertEqual(expected, actual)

    _do_test(expected={})

    _do_test(langs=['java', 'python'],
             source_root_parents=['src', 'example/src'],
             expected={
               'src/java': ('java',), 'src/python': ('python',),
               'example/src/java': ('java',), 'example/src/python': ('python',)
             })

    _do_test(source_roots={ 'src/jvm': ('java', 'scala'), 'src/py': ('python',) },
             expected={ 'src/jvm': ('java', 'scala'), 'src/py': ('python',) })

    _do_test(langs=['java', 'python'],
             source_root_parents=['src', 'example/src'],
             source_roots={ 'src/jvm': ('java', 'scala'), 'src/py': ('python',) },
             expected={
               'src/java': ('java',), 'src/python': ('python',),
               'example/src/java': ('java',), 'example/src/python': ('python',),
               'src/jvm': ('java', 'scala'), 'src/py': ('python',)
             })

    _do_test(langs=['java', 'python'], test_root_parents=['src', 'example/src'],
             test_roots={ 'src/jvm': ('java', 'scala'), 'src/py': ('python',) },
             expected={
               'src/java': ('java',), 'src/python': ('python',),
               'example/src/java': ('java',), 'example/src/python': ('python',),
               'src/jvm': ('java', 'scala'), 'src/py': ('python',)
             })

  def test_source_root_trie(self):
    trie = SourceRootTrie()
    self.assertIsNone(trie.find('src/java/org/pantsbuild/foo/Foo.java'))

    trie.add_pattern('src/java', ('java',))
    self.assertEquals(('src/java', ('java',)),
                      trie.find('src/java/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(('my/project/src/java', ('java',)),
                      trie.find('my/project/src/java/org/pantsbuild/foo/Foo.java'))

    trie.add_pattern('src/python', ('python',))
    self.assertEquals(('src/java', ('java',)),
                      trie.find('src/java/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(('my/project/src/java', ('java',)),
                      trie.find('my/project/src/java/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(('src/python', ('python',)),
                      trie.find('src/python/pantsbuild/foo/foo.py'))
    self.assertEquals(('my/project/src/python', ('python',)),
                      trie.find('my/project/src/python/org/pantsbuild/foo/foo.py'))

    # Verify that we take the first matching prefix.
    self.assertEquals(('src/java', ('java',)),
                      trie.find('src/java/src/python/Foo.java'))

    # Test fixed patterns.
    trie.add_fixed('src/scala', ('scala',))
    self.assertEquals(('src/scala', ('scala',)),
                      trie.find('src/scala/org/pantsbuild/foo/Foo.scala'))
    self.assertIsNone(trie.find('my/project/src/scala/org/pantsbuild/foo/Foo.scala'))

    # Test multiple langs.
    trie.add_pattern('src/jvm', ('java', 'scala'))

    self.assertEquals(('src/jvm', ('java', 'scala')),
                      trie.find('src/jvm/org/pantsbuild/foo/Foo.java'))
    self.assertEquals(('src/jvm', ('java', 'scala')),
                      trie.find('src/jvm/org/pantsbuild/foo/Foo.scala'))

    # Test long pattern.
    trie.add_pattern('src/main/long/path/java', ('java',))
    self.assertEquals(('my/project/src/main/long/path/java', ('java',)),
                      trie.find('my/project/src/main/long/path/java/org/pantsbuild/foo/Foo.java'))

  def test_all_roots(self):
    self.create_dir('src/java')
    self.create_dir('src/python')
    self.create_dir('src/example/java')
    self.create_dir('src/example/python')
    self.create_dir('my/project/src/java')
    self.create_dir('not/a/srcroot/java')

    options = {
      'langs': ['java', 'python', 'nonexistent'],
      'source_root_parents': ['src/', 'src/example'],
    }
    options.update(self.options[''])  # We need inherited values for pants_workdir etc.

    source_roots = create_subsystem(SourceRootConfig, **options).get_source_roots()
    self.assertEquals({('src/java', ('java',)),
                       ('src/python', ('python',)),
                       ('src/example/java', ('java',)),
                       ('src/example/python', ('python',)),
                       ('my/project/src/java', ('java',))},
                      set(source_roots.all_roots()))
