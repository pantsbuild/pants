# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import namedtuple

from six.moves import range

from pants.base.project_tree_factory import get_project_tree
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method, memoized_property


class SourceRootCategories(object):
  UNKNOWN = 'unknown'
  SOURCE = 'source'
  TEST = 'test'
  THIRDPARTY = 'thirdparty'
  ALL = [UNKNOWN, SOURCE, TEST, THIRDPARTY]


SourceRoot = namedtuple('_SourceRoot', ['path', 'langs', 'category'])


class SourceRootFactory(object):
  """Creates source roots that respect language canonicalizations."""

  def __init__(self, lang_canonicalizations):
    """Creates a source root factory that enforces the given `lang_canonicalizations`.

    :param dict lang_canonicalizations: a mapping from language nicknames to the canonical language
                                        names the nickname could represent.
    """
    self._lang_canonicalizations = lang_canonicalizations

  def _canonicalize_langs(self, langs):
    for lang in (langs or ()):
      canonicalized = self._lang_canonicalizations.get(lang, (lang,))
      for canonical in canonicalized:
        yield canonical

  def create(self, relpath, langs, category):
    """Return a source root at the given `relpath` for the given `langs` and `category`.

    :returns: :class:`SourceRoot`.
    """
    return SourceRoot(relpath, tuple(self._canonicalize_langs(langs)), category)


class SourceRoots(object):
  """An interface for querying source roots."""

  def __init__(self, source_root_config):
    """Create an object for querying source roots via patterns in a trie.

    :param source_root_config: The SourceRootConfig for the source root patterns to query against.

    Non-test code should not instantiate directly. See SourceRootConfig.get_source_roots().
    """
    self._trie = source_root_config.create_trie()
    self._source_root_factory = source_root_config.source_root_factory
    self._options = source_root_config.get_options()

  def add_source_root(self, path, langs=tuple(), category=SourceRootCategories.UNKNOWN):
    """Add the specified fixed source root, which must be relative to the buildroot.

    Useful in a limited set of circumstances, e.g., when unpacking sources from a jar with
    unknown structure.  Tests should prefer to use dirs that match our source root patterns
    instead of explicitly setting source roots here.
    """
    self._trie.add_fixed(path, langs, category)

  def find(self, target):
    """Find the source root for the given target, or None.

    :param target: Find the source root for this target.
    :return: A SourceRoot instance.
    """
    return self.find_by_path(target.address.spec_path)

  def find_by_path(self, path):
    """Find the source root for the given path, or None.

    :param path: Find the source root for this path, relative to the buildroot.
    :return: A SourceRoot instance, or None if the path is not located under a source root
             and `unmatched==fail`.
    """
    matched = self._trie.find(path)
    if matched:
      return matched
    elif self._options.unmatched == 'fail':
      return None
    elif self._options.unmatched == 'create':
      # If no source root is found, use the path directly.
      # TODO: Remove this logic. It should be an error to have no matching source root.
      return SourceRoot(path, [], SourceRootCategories.UNKNOWN)

  def all_roots(self):
    """Return all known source roots.

    Returns a generator over (source root, list of langs, category) triples.

    Note: Requires a directory walk to match actual directories against patterns.
    However we don't descend into source roots, once found, so this should be fast in practice.
    Note: Does not follow symlinks.
    """
    project_tree = get_project_tree(self._options)

    fixed_roots = set()
    for root, langs, category in self._trie.fixed():
      if project_tree.exists(root):
        yield self._source_root_factory.create(root, langs, category)
      fixed_roots.add(root)

    for relpath, dirnames, _ in project_tree.walk('', topdown=True):
      match = self._trie.find(relpath)
      if match:
        if not any(fixed_root.startswith(relpath) for fixed_root in fixed_roots):
          yield match  # Found a source root not a prefix of any fixed roots.
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

  # TODO: When we have a proper model of the concept of a language, these should really be
  # gathered from backends.
  _DEFAULT_LANG_CANONICALIZATIONS = {
    'jvm': ('java', 'scala'),
    'protobuf': ('proto',),
    'py': ('python',),
    'golang': ('go',),
  }

  _DEFAULT_SOURCE_ROOT_PATTERNS = [
    'src/*',
    'src/main/*',
  ]

  _DEFAULT_TEST_ROOT_PATTERNS = [
    'test/*',
    'tests/*',
    'src/test/*',
  ]

  _DEFAULT_THIRDPARTY_ROOT_PATTERNS = [
    '3rdparty/*',
    '3rd_party/*',
    'thirdparty/*',
    'third_party/*',
  ]

  _DEFAULT_SOURCE_ROOTS = {
    # Our default patterns will detect src/go as a go source root.
    # However a typical repo might have src/go in the GOPATH, meaning src/go/src is the
    # actual source root (the root of the package namespace).
    # These fixed source roots will correct the patterns' incorrect guess.
    'src/go/src': ('go',),
    'src/main/go/src': ('go',),
  }

  _DEFAULT_TEST_ROOTS = {
  }

  _DEFAULT_THIRDPARTY_ROOTS = {
  }

  @classmethod
  def register_options(cls, register):
    super(SourceRootConfig, cls).register_options(register)
    register('--unmatched', choices=['create', 'fail'], default='create', advanced=True,
             help='Configures the behavior when sources are defined outside of any configured '
                  'source root. `create` will cause a source root to be implicitly created at '
                  'the definition location of the sources; `fail` will trigger an error.')
    register('--lang-canonicalizations', metavar='<map>', type=dict,
             default=cls._DEFAULT_LANG_CANONICALIZATIONS, advanced=True,
             help='Map of language aliases to their canonical names.')

    pattern_help_fmt = ('A list of source root patterns for {} code. Use a "*" wildcard path '
                        'segment to match the language name, which will be canonicalized.')
    register('--source-root-patterns', metavar='<list>', type=list,
             default=cls._DEFAULT_SOURCE_ROOT_PATTERNS, advanced=True,
             help=pattern_help_fmt.format('source'))
    register('--test-root-patterns', metavar='<list>', type=list,
             default=cls._DEFAULT_TEST_ROOT_PATTERNS, advanced=True,
             help=pattern_help_fmt.format('test'))
    register('--thirdparty-root-patterns', metavar='<list>', type=list,
             default=cls._DEFAULT_THIRDPARTY_ROOT_PATTERNS, advanced=True,
             help=pattern_help_fmt.format('third-party'))

    fixed_help_fmt = ('A map of source roots for {} code to list of languages. '
                      'Useful when you want to enumerate fixed source roots explicitly, '
                      'instead of relying on patterns.')
    register('--source-roots', metavar='<map>', type=dict,
             default=cls._DEFAULT_SOURCE_ROOTS, advanced=True,
             help=fixed_help_fmt.format('source'))
    register('--test-roots', metavar='<map>', type=dict,
             default=cls._DEFAULT_TEST_ROOTS, advanced=True,
             help=fixed_help_fmt.format('test'))
    register('--thirdparty-roots', metavar='<map>', type=dict,
             default=cls._DEFAULT_THIRDPARTY_ROOTS, advanced=True,
             help=fixed_help_fmt.format('third-party'))

  @memoized_method
  def get_source_roots(self):
    return SourceRoots(self)

  def create_trie(self):
    """Create a trie of source root patterns from options.

    :returns: :class:`SourceRootTrie`
    """
    trie = SourceRootTrie(self.source_root_factory)
    options = self.get_options()

    for category in SourceRootCategories.ALL:
      # Add patterns.
      for pattern in options.get('{}_root_patterns'.format(category), []):
        trie.add_pattern(pattern, category)
      # Add fixed source roots.
      for path, langs in options.get('{}_roots'.format(category), {}).items():
        trie.add_fixed(path, langs, category)

    return trie

  @memoized_property
  def source_root_factory(self):
    """Creates source roots that respects language canonicalizations.

    :returns: :class:`SourceRootFactory`
    """
    return SourceRootFactory(self.get_options().lang_canonicalizations)


class SourceRootTrie(object):
  """A trie for efficiently finding the source root for a path.

  Finds the first outermost pattern that matches. E.g., the pattern src/* will match
  my/project/src/python/src/java/java.py on src/python, not on src/java.

  Implements fixed source roots by prepending a '^/' to them, and then prepending a '^' key to
  the path we're matching. E.g., ^/src/java/foo/bar will match both the fixed root ^/src/java and
  the pattern src/java, but ^/my/project/src/java/foo/bar will match only the pattern.
  """
  class InvalidPath(Exception):
    def __init__(self, path, reason):
      super(SourceRootTrie.InvalidPath, self).__init__(
        'Invalid source root path or pattern: {}. Reason: {}.'.format(path, reason))

  class Node(object):
    def __init__(self):
      self.children = {}
      self.langs = tuple()
      self.category = None  # One of SourceRootCategories, or None if this isn't a terminal node.
      self.is_terminal = False
      # We need an explicit terminal flag because not all terminals are leaf nodes,  e.g.,
      # if we have patterns src/* and src/main/* then the '*' is a terminal (for the first pattern)
      # but not a leaf.

    def get_child(self, key, langs):
      """Return the child node for the given key, or None if no such child.

      :param key: The child to return.
      :param langs: An output parameter which we update with any langs associated with the child.
      """
      # An exact match takes precedence over a wildcard match, to support situations such as
      # src/* and src/main/*.
      ret = self.children.get(key)
      if ret:
        langs.update(ret.langs)
      elif key != '^':
        ret = self.children.get('*')
        if ret:
          langs.add(key)
      return ret

    def new_child(self, key):
      child = SourceRootTrie.Node()
      self.children[key] = child
      return child

    def subpatterns(self):
      if self.children:
        for key, child in self.children.items():
          for sp, langs, category in child.subpatterns():
            if sp:
              yield os.path.join(key, sp), langs, category
            else:
              yield key, langs, category
      else:
        yield '', self.langs, self.category

  def __init__(self, source_root_factory):
    self._source_root_factory = source_root_factory
    self._root = SourceRootTrie.Node()

  def add_pattern(self, pattern, category=SourceRootCategories.UNKNOWN):
    """Add a pattern to the trie."""
    self._do_add_pattern(pattern, tuple(), category)

  def add_fixed(self, path, langs, category=SourceRootCategories.UNKNOWN):
    """Add a fixed source root to the trie."""
    if '*' in path:
      raise self.InvalidPath(path, 'fixed path cannot contain the * character')
    fixed_path = os.path.join('^', path) if path else '^'
    self._do_add_pattern(fixed_path, tuple(langs), category)

  def fixed(self):
    """Returns a list of just the fixed source roots in the trie."""
    for key, child in self._root.children.items():
      if key == '^':
        return list(child.subpatterns())
    return []

  def _do_add_pattern(self, pattern, langs, category):
    if pattern != os.path.normpath(pattern):
      raise self.InvalidPath(pattern, 'must be a normalized path')
    keys = pattern.split(os.path.sep)

    node = self._root
    for key in keys:
      child = node.children.get(key)  # Can't use get_child, as we don't want to wildcard-match.
      if not child:
        child = node.new_child(key)
      node = child
    node.langs = langs
    node.category = category
    node.is_terminal = True

  def find(self, path):
    """Find the source root for the given path."""
    keys = ['^'] + path.split(os.path.sep)
    for i in range(len(keys)):
      # See if we have a match at position i.  We have such a match if following the path
      # segments into the trie, from the root, leads us to a terminal.
      node = self._root
      langs = set()
      j = i
      while j < len(keys):
        child = node.get_child(keys[j], langs)
        if child is None:
          break
        else:
          node = child
          j += 1
      if node.is_terminal:
        if j == 1:  # The match was on the root itself.
          path = ''
        else:
          path = os.path.join(*keys[1:j])
        return self._source_root_factory.create(path, langs, node.category)
      # Otherwise, try the next value of i.
    return None
