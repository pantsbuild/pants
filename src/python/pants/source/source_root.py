# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from six.moves import range

from pants.base.build_environment import get_buildroot
from pants.option.custom_types import dict_option, list_option
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method


class SourceRoots(object):
  """An interface for querying source roots."""

  @classmethod
  @memoized_method
  def instance(cls):
    """A singleton instance of SourceRoots.

    Required temporarily, while migrating from the old source roots registry mechanism.
    Tasks should be able to access a SourceRoots from context, so we may be able to get rid of
    this explicit singleton.
    """
    return SourceRootConfig.global_instance().get_source_roots()

  @classmethod
  def reset(cls):
    """Reset all source roots to empty. Only intended for testing."""
    # TODO: Remove this after migration, when tests access source roots via context rather
    # than from the singleton.
    cls.instance.forget(cls)

  def __init__(self, source_root_config):
    """Create an object for querying source roots via patterns in a trie.

    :param source_root_config: The SourceRootConfig for the source root patterns to query against.

    Non-test code should not instantiate directly. See SourceRootConfig.get_source_roots().
    """
    self._trie = source_root_config.create_trie()
    self._options = source_root_config.get_options()

  def register(self, path, langs=tuple()):
    """TEMPORARY registration method, during transition from old to new implementation."""
    self._trie.add_fixed(path, langs)

  def find(self, target):
    """Find the source root for the given target.

    :param target: Find the source root for this target.
    :return: A (source root, list of langs) pair.
    """
    target_path = target.address.spec_path
    # If no source root is found, use the target's path.
    # TODO: Remove this logic. It should be an error to have no matching source root.
    return self.find_by_path(target_path) or (target_path, [])

  def find_by_path(self, path):
    """Find the source root for the given path.

    :param path: Find the source root for this path.
    :return: A (source root, list of langs) pair, or None if no matching source root found.
    """
    # TODO: Is this normalization necessary? Shouldn't all paths here be relative already?
    if os.path.isabs(path):
      path = os.path.relpath(path, get_buildroot())
    return self._trie.find(path)

  def all_roots(self):
    """Return all known source roots.

    Returns a generator over (source root, list of langs) pairs.

    Note: Requires a directory walk to match actual directories against patterns.
    However we don't descend into source roots, once found, so this should be fast in practice.
    Note: Does not follow symlinks.
    """
    buildroot = get_buildroot()
    # Note: If we support other SCMs in the future, add their metadata dirs here if relevant.
    ignore = {'.git'}.union({os.path.relpath(self._options[k], buildroot) for k in
                            ['pants_workdir', 'pants_supportdir', 'pants_distdir']})

    for dirpath, dirnames, _ in os.walk(buildroot, topdown=True):
      relpath = os.path.relpath(dirpath, buildroot)
      if relpath in ignore:
        del dirnames[:]  # Don't descend into ignored dirs.
      else:
        match = self._trie.find(relpath)
        if match:
          yield match  # Found a source root.
          del dirnames[:]  # Don't continue to walk into it.


class SourceRootConfig(Subsystem):
  """Configuration for roots of source trees.

  We detect source roots based on a list of source root patterns.  E.g., if we have src/java
  as a pattern then any directory that ends with src/java will be considered a source root:
  src/java, my/project/src/java etc.

  A source root may be associated with one or more 'languages'. E.g., src/java can be associated
  with java, and src/jvm can be associated with java and scala. Note that this is a generalized
  concept of 'language'. For example 'resources' is a language in this sense.

  We specify source roots in three ways:

  1. We autoconstruct patterns by appending language names to parent dirs. E.g., for languages
     'java' and 'python', and parents 'src' and 'example/src', we construct the patterns
     'src/java', 'src/python', 'example/src/java' and 'example/src/python'.  These are of course
     associated with the appropriate language.

  2. We can explicitly specify a mapping from source root pattern to language(s). E.g.,
     {
       'src/jvm': ['java', 'scala'],
       'src/py': ['python']
     }

  3. We can also bypass the pattern mechanism altogether and specify a list of fixed source roots.
     E.g., src/java will match just <buildroot>/src/java, and not <buildroot>/some/dir/src/java.

  Note that we distinguish between 'source roots' and 'test roots'. All the above holds for both.
  We don't currently use this distinction in a useful way, but we may in the future, and we don't
  want to then require everyone to modify their source root declarations, so we implement the
  distinction now.

  Note also that there's no harm in specifying source root patterns that don't exist in your repo,
  within reason.  This means that in most cases the defaults below will be sufficient and repo
  owners will not need to explicitly specify source root patterns at all.
  """

  options_scope = 'source'

  _DEFAULT_LANGS = [
    'android',
    'antlr',
    'cpp',
    'go',
    'java',
    'node',
    'protobuf',
    'py',
    'python',
    'resources',
    'scala',
    'thrift',
    'wire',
  ]

  _DEFAULT_SOURCE_ROOT_PARENTS = [
    'src',
    'src/main',
    '3rdparty',
  ]

  _DEFAULT_TEST_ROOT_PARENTS = [
    'test',
    'tests',
    'src/test',
  ]

  _DEFAULT_SOURCE_ROOT_PATTERNS = {
    'src/jvm': ['java', 'scala'],
  }

  _DEFAULT_TEST_ROOT_PATTERNS = {
    'test/jvm': ['java', 'scala'],
    'tests/jvm': ['java', 'scala'],
  }

  @classmethod
  def register_options(cls, register):
    super(SourceRootConfig, cls).register_options(register)
    register('--langs', metavar='<list>', type=list_option,
             default=cls._DEFAULT_LANGS, advanced=True,
             help='A list of supported language names to autoconstruct source root patterns from.')

    register('--source-root-parents', metavar='<list>', type=list_option,
             default=cls._DEFAULT_SOURCE_ROOT_PARENTS, advanced=True,
             help='A list of parent dirs to autoconstruct source root patterns from. '
                  'The constructed roots are of the pattern <parent>/<lang>, where <lang> is one '
                  'of the languages specified by the --langs option.')
    register('--test-root-parents', metavar='<list>', type=list_option,
             default=cls._DEFAULT_TEST_ROOT_PARENTS, advanced=True,
             help='A list of parent dirs to autoconstruct test root patterns from. '
                  'The constructed roots are of the pattern <parent>/<lang>, where <lang> is one '
                  'of the languages specified by the --langs option.')

    register('--source-root-patterns', metavar='<map>', type=dict_option,
             default=cls._DEFAULT_SOURCE_ROOT_PATTERNS, advanced=True,
             help='A mapping from source root pattern to list of languages of source code found '
                  'under paths matching that pattern. Useful when the autoconstructed source root'
                  'patterns are not sufficient.')
    register('--test-root-patterns', metavar='<map>', type=dict_option,
             default=cls._DEFAULT_TEST_ROOT_PATTERNS, advanced=True,
             help='A mapping from test root pattern to list of languages of test code found '
                  'under paths matching that pattern. Useful when the autoconstructed test root'
                  'patterns are not sufficient.')

    register('--source-roots', metavar='<map>', type=dict_option, advanced=True,
             help='A map of source roots to list of languages.  Useful when you want to enumerate '
                  'fixed source roots explicitly, instead of relying on patterns.')
    register('--test-roots', metavar='<map>', type=dict_option, advanced=True,
             help='A map of test roots to list of languages.  Useful when you want to enumerate '
                  'fixed test roots explicitly, instead of relying on patterns.')

  def get_source_roots(self):
    return SourceRoots(self)

  def generate_source_root_pattern_mappings(self):
    """Generate source root patterns from options.

    Does not currently distinguish between source (i.e., non-test) and test roots, and yields them
    both as "source roots", which is correct for our current uses of source roots.
    TODO: Put the distinction between test and non-test source roots to good use.
    """
    options = self.get_options()

    def gen_from_options(prefix):
      for parent in options[prefix + '_root_parents'] or []:
        for lang in options.langs or []:
          yield os.path.join(parent, lang), (lang,)
      for pattern, langs in (options[prefix + '_root_patterns'] or {}).items():
        yield pattern, tuple(langs)

    for x in gen_from_options('source'):
      yield x
    for x in gen_from_options('test'):
      yield x

  def create_trie(self):
    """Create a trie of source root patterns from options."""
    trie = SourceRootTrie()

    # First add all patterns.
    for pattern, langs in self.generate_source_root_pattern_mappings():
      trie.add_pattern(pattern, langs)

    # Now add all fixed source roots.
    def gen_fixed_from_options(prefix):
      for path, langs in (self.get_options()[prefix + '_roots'] or {}).items():
        trie.add_fixed(path, langs)

    gen_fixed_from_options('source')
    gen_fixed_from_options('test')

    return trie


class SourceRootTrie(object):
  """A trie for efficiently finding the source root for a path.

  Finds the first outermost pattern that matches. E.g., my/project/src/python/src/java/java.py
  will match the pattern src/python, not src/java.

  Implements fixed source roots by prepending a '^/' to them, and then prepending a '^' key to
  the path we're matching. E.g., ^/src/java/foo/bar will match both the fixed root ^/src/java and
  the pattern src/java, but ^/my/project/src/java/foo/bar will match only the pattern.
  """
  class Node(object):
    def __init__(self):
      self.children = {}
      self.langs = tuple()  # Relevant only if this is a leaf node.

    def get_child(self, key):
      return self.children.get(key)

    def new_child(self, key):
      child = SourceRootTrie.Node()
      self.children[key] = child
      return child

    def is_leaf(self):
      return len(self.children) == 0

  def __init__(self):
    self._root = SourceRootTrie.Node()

  def add_pattern(self, pattern, langs=None):
    """Add a pattern to the trie."""
    keys = pattern.split(os.path.sep)
    node = self._root
    for key in keys:
      child = node.get_child(key)
      if not child:
        child = node.new_child(key)
      node = child
    node.langs = tuple(langs or [])

  def add_fixed(self, path, langs=None):
    """Add a fixed source root to the trie."""
    self.add_pattern(os.path.join('^', path), tuple(langs))

  def find(self, path):
    """Find the source root for the given path."""
    keys = ['^'] + path.split(os.path.sep)
    for i in range(0, len(keys)):
      # See if we have a match at position i.  We have such a match if following the path
      # segments into the trie, from the root, leads us to a leaf.
      node = self._root
      for j in range(i, len(keys)):
        child = node.get_child(keys[j])
        if child is None:
          break  # We can't continue.  Try the next value of i.
        elif child.is_leaf():
          # We found a leaf, so this source root pattern applies.  Return the entire prefix, up
          # to the end of the pattern, as the source root.
          # Note that the range starts from 1, to skip the '^' we added.
          return os.path.join(*keys[1:j + 1]), child.langs
        else:
          node = child
    return None
