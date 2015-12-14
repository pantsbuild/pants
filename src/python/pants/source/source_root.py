# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import namedtuple

from six.moves import range

from pants.base.build_environment import get_buildroot
from pants.option.custom_types import dict_option, list_option
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method


SourceRoot = namedtuple('_SourceRoot', ['path', 'langs'])


class SourceRoots(object):
  """An interface for querying source roots."""

  def __init__(self, source_root_config):
    """Create an object for querying source roots via patterns in a trie.

    :param source_root_config: The SourceRootConfig for the source root patterns to query against.

    Non-test code should not instantiate directly. See SourceRootConfig.get_source_roots().
    """
    self._trie = source_root_config.create_trie()
    self._options = source_root_config.get_options()

  def add_source_root(self, path, langs=tuple()):
    """Add the specified fixed source root.

    Useful in a limited set of circumstances, e.g., when unpacking sources from a jar with
    unknown structure.  Tests should prefer to use dirs that match our source root patterns
    instead of explicitly setting source roots here.
    """
    self._trie.add_fixed(path, langs)

  def find(self, target):
    """Find the source root for the given target.

    :param target: Find the source root for this target.
    :return: A SourceRoot instance.
    """
    target_path = target.address.spec_path
    # If no source root is found, use the target's path.
    # TODO: Remove this logic. It should be an error to have no matching source root.
    return self.find_by_path(target_path) or SourceRoot(target_path, [])

  def find_by_path(self, path):
    """Find the source root for the given path.

    :param path: Find the source root for this path.
    :return: A SourceRoot instance, or None if no matching source root found.
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

  # TODO: When we have a proper model of the concept of a language, these should really be
  # gathered from backends.
  _DEFAULT_LANG_CANONICALIZATIONS = {
    'jvm': ('java', 'scala'),
    'protobuf': ('proto',),
    'py': ('python',)
  }

  _DEFAULT_SOURCE_ROOT_PATTERNS = [
    '3rdparty/*',
    'src/*',
    'src/main/*',
  ]

  _DEFAULT_TEST_ROOT_PATTERNS = {
    'test/*',
    'tests/*',
    'src/test/*'
  }

  _DEFAULT_SOURCE_ROOTS = {
    # Go requires some special-case handling of source roots.  In particular, go buildgen assumes
    # that there's a single source root for local code and (optionally) a single source root
    # for remote code.  This fixed source root shows how to capture that distinction.
    # Go repos may need to add their own appropriate special cases in their pants.ini, until we fix this hack.
    # TODO: Treat third-party/remote code as a separate category (akin to 'source' and 'test').
    # Then this hack won't be necessary.
    '3rdparty/go': ('go_remote', ),
    'contrib/go/examples/3rdparty/go': ('go_remote', )
  }

  _DEFAULT_TEST_ROOTS = {
  }

  @classmethod
  def register_options(cls, register):
    super(SourceRootConfig, cls).register_options(register)
    register('--lang-canonicalizations', metavar='<map>', type=dict_option,
             default=cls._DEFAULT_LANG_CANONICALIZATIONS, advanced=True,
             help='Map of language aliases to their canonical names.')
    register('--source-root-patterns', metavar='<list>', type=list_option,
             default=cls._DEFAULT_SOURCE_ROOT_PATTERNS, advanced=True,
             help='A list of source root patterns. Use a "*" wildcard path segment to match the '
                  'language name, which will be canonicalized.')
    register('--test-root-patterns', metavar='<list>', type=list_option,
             default=cls._DEFAULT_TEST_ROOT_PATTERNS, advanced=True,
             help='A list of source root patterns. Use a "*" wildcard path segment to match the '
                  'language name, which will be canonicalized.')

    register('--source-roots', metavar='<map>', type=dict_option,
             default=cls._DEFAULT_SOURCE_ROOTS, advanced=True,
             help='A map of source roots to list of languages.  Useful when you want to enumerate '
                  'fixed source roots explicitly, instead of relying on patterns.')
    register('--test-roots', metavar='<map>', type=dict_option,
             default=cls._DEFAULT_TEST_ROOTS, advanced=True,
             help='A map of test roots to list of languages.  Useful when you want to enumerate '
                  'fixed test roots explicitly, instead of relying on patterns.')

  @memoized_method
  def get_source_roots(self):
    return SourceRoots(self)

  def create_trie(self):
    """Create a trie of source root patterns from options."""
    options = self.get_options()
    trie = SourceRootTrie(options.lang_canonicalizations)

    # Add patterns.
    for pattern in options.source_root_patterns or []:
      trie.add_pattern(pattern)
    for pattern in options.test_root_patterns or []:
      trie.add_pattern(pattern)

    # Now add all fixed source roots.
    for path, langs in (options.source_roots or {}).items():
      trie.add_fixed(path, langs)
    for path, langs in (options.test_roots or {}).items():
      trie.add_fixed(path, langs)

    return trie


class SourceRootTrie(object):
  """A trie for efficiently finding the source root for a path.

  Finds the first outermost pattern that matches. E.g., the pattern src/* will match
  my/project/src/python/src/java/java.py on src/python, not on src/java.

  Implements fixed source roots by prepending a '^/' to them, and then prepending a '^' key to
  the path we're matching. E.g., ^/src/java/foo/bar will match both the fixed root ^/src/java and
  the pattern src/java, but ^/my/project/src/java/foo/bar will match only the pattern.
  """
  class Node(object):
    def __init__(self):
      self.children = {}
      self.langs = tuple()
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
      else:
        ret = self.children.get('*')
        if ret:
          langs.add(key)
      return ret

    def new_child(self, key):
      child = SourceRootTrie.Node()
      self.children[key] = child
      return child

  def __init__(self, lang_canonicalizations):
    self._lang_canonicalizations = lang_canonicalizations
    self._root = SourceRootTrie.Node()

  def add_pattern(self, pattern):
    """Add a pattern to the trie."""
    self._do_add_pattern(pattern, tuple())

  def add_fixed(self, path, langs=None):
    """Add a fixed source root to the trie."""
    self._do_add_pattern(os.path.join('^', path), tuple(langs))

  def _do_add_pattern(self, pattern, langs):
    keys = pattern.split(os.path.sep)
    node = self._root
    for key in keys:
      child = node.children.get(key)  # Can't use get_child, as we don't want to wildcard-match.
      if not child:
        child = node.new_child(key)
      node = child
    node.langs = langs
    node.is_terminal = True

  def _canonicalize_langs(self, langs):
    ret = []
    for lang in langs or []:
      canonicalized = self._lang_canonicalizations.get(lang)
      if canonicalized:
        ret.extend(canonicalized)
      else:
        ret.append(lang)
    return tuple(ret)

  def find(self, path):
    """Find the source root for the given path."""
    keys = ['^'] + path.split(os.path.sep)
    for i in range(len(keys)):
      # See if we have a match at position i.  We have such a match if following the path
      # segments into the trie, from the root, leads us to a leaf.
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
        return SourceRoot(os.path.join(*keys[1:j]), self._canonicalize_langs(langs))
      # Otherwise, try the next value of i.
    return None
