# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException


class SourceRootTree(object):
  """A helper data structure for SourceRoot that creates a tree from the SourceRoot paths
  where each subdirectory is a node.  This helps to quickly determine which types are
  allowed along a path.
  """

  class DuplicateSourceRootError(Exception):
    pass

  class NestedSourceRootError(Exception):
    pass


  class Node(object):
    """Node in the tree that represents a directory"""

    def __init__(self, key):
      self.key = key
      self.children = {}
      self.is_leaf = False
      self.types = None

    def set_leaf(self, types):
      self.is_leaf = True
      self.types = types

    def get(self, key):
      return self.children.get(key)

    def get_or_add(self, key):
      child = self.get(key)
      if not child:
        child = SourceRootTree.Node(key)
        self.children[key] = child
      return child

    def __eq__(self, other):
      return self.key == other.key


  def __init__(self):
    self._root = self.Node(key="ROOT")

  def add_root(self, source_root, types):
    """Add a single source root to the tree.

    :param string source_root:  a path in the source root tree
    :param types: target types allowed at this source root
    :type types: set of classes derived from Target
    """
    curr_node = self._root
    dir_list = os.path.normpath(source_root).split(os.path.sep)
    for subdir in dir_list:
      curr_node = curr_node.get_or_add(subdir)

    if curr_node.is_leaf and types != curr_node.types:
      raise self.DuplicateSourceRootError("{source_root} already exists in tree."
                                          .format(source_root=source_root))
    elif curr_node.children:
      # TODO(Eric Ayers) print the list of conflicting source_roots already registered.
      raise self.NestedSourceRootError("{source_root} is nested inside an existing"
                                       "source_root."
                                       .format(source_root=source_root))
    curr_node.set_leaf(types)

  def get_root_and_types(self, path):
    """Finds the source root that matches the prefix of the given path.

    This method is intended primariy for debugging.

    :param string path: a source root path starting from the root of the repo.
    :returns: the source_root, set of types valid along that path, or None if no SourceRoot has been registered.
    """
    found = curr_node = self._root
    found_path = []
    dir_list = os.path.normpath(path).split(os.path.sep)
    for subdir in dir_list:
      curr_node = curr_node.get(subdir)
      if not curr_node:
        break
      found = curr_node
      found_path.append(subdir)

    if found.is_leaf:
      return os.path.sep.join(found_path), found.types
    return None, None

  def _dump(self):
    """:returns: a text version of the tree for debugging"""

    def do_dump(node, buf, level):
      buf += "{pad}{key} leaf={is_leaf}\n".format(pad=''.rjust(level),
                                                  key=node.key, is_leaf=node.is_leaf)
      for child in node.children.values():
        buf += do_dump(child, buf, level + 1)
      return buf

    return do_dump(self._root, '', 0)


class SourceRoot(object):
  """Allows registration of a source root for a set of targets.

  A source root is the base path sources for a particular language are found relative to.
  Generally compilers or interpreters for the source will expect sources relative to a base path
  and a source root allows calculation of the correct relative paths.

  E.g., a Java compiler probably expects to find ``.java`` files for
  ``package com.twitter.common.net`` in ``*something*/com/twitter/common/net``.
  The ``source_root`` command specifies that *something*.

  It is illegal to have nested source roots.
  """
  _ROOTS_BY_TYPE = {}
  _TYPES_BY_ROOT = {}
  _SEARCHED = set()
  _SOURCE_ROOT_TREE = SourceRootTree()

  def __init__(self, parse_context):
    self.rel_path = parse_context.rel_path

  def __call__(self, basedir, *allowed_target_types):
    allowed_target_types = [proxy._addressable_type.get_target_type()
                            for proxy in allowed_target_types]
    SourceRoot.register(os.path.join(self.rel_path, basedir), *allowed_target_types)

  def here(self, *allowed_target_types):
    """Registers the cwd as a source root for the given target types.

    :param allowed_target_types: instances of AddressableCallProxy to register for this BUILD file.
    """
    allowed_target_types = [proxy._addressable_type.get_target_type()
                            for proxy in allowed_target_types]
    SourceRoot.register(self.rel_path, *allowed_target_types)

  @classmethod
  def reset(cls):
    """Reset all source roots to empty. Only intended for testing."""
    cls._ROOTS_BY_TYPE = {}
    cls._TYPES_BY_ROOT = {}
    cls._SEARCHED = set()
    cls._SOURCE_ROOT_TREE = SourceRootTree()

  @classmethod
  def find(cls, target):
    """Finds the source root for the given target.

    :param Target target: the target whose source_root you are querying.
    :returns: the source root that is a prefix of the target, or the parent directory of the
    target's BUILD file if none is registered.
    """
    target_path = target.address.spec_path
    found_source_root, allowed_types = cls._SOURCE_ROOT_TREE.get_root_and_types(target_path)
    if not found_source_root:
      # If the source root is not registered, use the path from the spec.
      found_source_root = target_path

    if allowed_types and not isinstance(target, allowed_types):
      # TODO: Find a way to use the BUILD file aliases in the error message, instead
      # of target.__class__.__name__. E.g., java_tests instead of JavaTests.
      raise TargetDefinitionException(target,
                                      'Target type {target_type} not allowed under {source_root}'
                                      .format(target_type=target.__class__.__name__,
                                              source_root=found_source_root))
    return found_source_root

  @classmethod
  def types(cls, root):
    """:returns: the set of target types rooted at root."""
    return cls._TYPES_BY_ROOT[root]

  @classmethod
  def roots(cls, target_type):
    """":returns: the set of roots for given target type."""
    return cls._ROOTS_BY_TYPE[target_type]

  @classmethod
  def all_roots(cls):
    """:returns: a mapping from source roots to the associated target types."""
    return dict(cls._TYPES_BY_ROOT)

  @classmethod
  def register(cls, basedir, *allowed_target_types):
    """Registers the given basedir (relative to the buildroot) as a source root.

    :param string basedir: The base directory to resolve sources relative to.
    :param list allowed_target_types: Optional list of target types. If specified, we enforce that
      only targets of those types appear under this source root.
    """
    cls._register(basedir, *allowed_target_types)

  @classmethod
  def _register(cls, source_root_dir, *allowed_target_types):
    """Registers a source root.

    :param string source_root_dir: The source root directory against which we resolve source paths,
                     relative to the build root.
    :param list allowed_target_types: Optional list of target types. If specified, we enforce that
                          only targets of those types appear under this source root.
    """
    # Verify that source_root_dir doesn't reach outside buildroot.
    buildroot = os.path.normpath(get_buildroot())
    if source_root_dir.startswith(buildroot):
      abspath = os.path.normpath(source_root_dir)
    else:
      abspath = os.path.normpath(os.path.join(buildroot, source_root_dir))
    if not abspath.startswith(buildroot):
      raise ValueError('Source root %s is not under the build root %s' % (abspath, buildroot))
    source_root_dir = os.path.relpath(abspath, buildroot)

    types = cls._TYPES_BY_ROOT.get(source_root_dir)
    if types is None:
      types = OrderedSet()
      cls._TYPES_BY_ROOT[source_root_dir] = types

    for allowed_target_type in allowed_target_types:
      types.add(allowed_target_type)
      roots = cls._ROOTS_BY_TYPE.get(allowed_target_type)
      if roots is None:
        roots = OrderedSet()
        cls._ROOTS_BY_TYPE[allowed_target_type] = roots
      roots.add(source_root_dir)

    cls._SOURCE_ROOT_TREE.add_root(source_root_dir, allowed_target_types)

