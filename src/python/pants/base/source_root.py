# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot
from pants.base.build_file_target_factory import BuildFileTargetFactory
from pants.base.build_manual import manual
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

    def set_leaf(self, types, mutable):
      self.is_leaf = True
      self.types = OrderedSet(types)
      self.mutable = mutable

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

  @staticmethod
  def _dir_list(path):
    normpath = os.path.normpath(path)
    return [] if normpath == '.' else normpath.split(os.path.sep)

  def __init__(self):
    self._root = self.Node(key="ROOT")

  def add_root(self, source_root, types, mutable=False):
    """Add a single source root to the tree.

    :param string source_root:  a path in the source root tree
    :param types: target types allowed at this source root
    :type types: set of classes derived from Target
    """
    curr_node = self._root
    for subdir in self._dir_list(source_root):
      curr_node = curr_node.get_or_add(subdir)

    if curr_node.is_leaf and types != curr_node.types:
      if mutable and curr_node.mutable:
        curr_node.types.update(types)
      else:
        raise self.DuplicateSourceRootError("{source_root} already exists in tree."
                                            .format(source_root=source_root))
    elif curr_node.children:
      # TODO(Eric Ayers) print the list of conflicting source_roots already registered.
      raise self.NestedSourceRootError("{source_root} is nested inside an existing "
                                       "source_root."
                                       .format(source_root=source_root))
    else:
      curr_node.set_leaf(types, mutable)

  def get(self, path):
    """
    :param string path: a source root path starting from the root of the repo
    :return: a Node and the source_root as a list of subdirectories if a source root is found, or
    None if no source root has been registered.
    """
    found = curr_node = self._root
    found_path = []
    for subdir in self._dir_list(path):
      curr_node = curr_node.get(subdir)
      if not curr_node:
        break
      found = curr_node
      found_path.append(subdir)
    if found.is_leaf:
      return found, found_path
    return None, None

  def get_root_and_types(self, path):
    """Finds the source root that matches the prefix of the given path.

    :param string path: a source root path starting from the root of the repo.
    :returns: the source_root, set of types valid along that path, or None if no source root has
    been registered.
    """
    found, found_path = self.get(path)
    if found:
      return os.path.sep.join(found_path), tuple(found.types)
    return None, None

  def get_root_siblings(self, path):
    """Find siblings to all source roots that are related to this path.

     This method will first find the source root to the supplied path, then find the siblings to
     that source root.  The siblings and the direct source root are returned.

    :param path: A path containing source
    :return: list of paths
    """
    found, dir_list = self.get(path)
    if not found:
      return []
    # The dir_list will always contain at least one entry.  Remove the last item to get the
    # parent of the source_root
    dir_list = dir_list[:-1]
    siblings = []
    # Walk to the parent node in the tree
    parent_node = self._root
    for curr_dir in dir_list:
      parent_node = parent_node.get(curr_dir)

    parent_path = os.path.sep.join(dir_list)
    for child_key in parent_node.children.keys():
      if parent_node.get(child_key).is_leaf:
        siblings.append(os.path.join(parent_path, child_key))
    return siblings

  def _dump(self):
    """:returns: a text version of the tree for debugging"""

    def do_dump(node, level):
      buf = "{pad}{key} leaf={is_leaf}\n".format(pad=''.rjust(level),
                                                 key=node.key, is_leaf=node.is_leaf)
      for child in node.children.values():
        buf += do_dump(child, level + 1)
      return buf

    return do_dump(self._root, 0)


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

  @classmethod
  @manual.builddict(factory=True)
  def factory(cls, parse_context):
    """Creates a ``SourceRoot`` valid for the given ``ParseContext``."""
    return cls(parse_context.rel_path)

  _ROOTS_BY_TYPE = {}
  _TYPES_BY_ROOT = {}
  _SEARCHED = set()
  _SOURCE_ROOT_TREE = SourceRootTree()

  def __init__(self, rel_path):
    self.rel_path = rel_path

  def __call__(self, basedir, *allowed_target_types):
    self._register_target_type_factories(os.path.join(self.rel_path, basedir),
                                         *allowed_target_types)

  def here(self, *allowed_target_types):
    """Registers the cwd as a source root for the given target types.

    :param allowed_target_types: Type factories to register for this BUILD file.
    """
    self._register_target_type_factories(self.rel_path, *allowed_target_types)

  def _register_target_type_factories(self, basedir, *target_type_factories):
    invalid_target_type_factories = [f for f in target_type_factories
                                     if not isinstance(f, BuildFileTargetFactory)]
    if invalid_target_type_factories:
      raise ValueError('The following are not valid target types for registering against the '
                       'source root at {}:\n\t{}'
                       .format(basedir, '\n\t'.join(map(str, invalid_target_type_factories))))

    allowed_target_types = set()
    for target_type_factory in target_type_factories:
      allowed_target_types.update(target_type_factory.target_types)
    self.register(basedir, *tuple(allowed_target_types))

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
    if found_source_root is None:  # NB: '' represents the buildroot, so we explicitly check None.
      # If the source root is not registered, use the path from the spec.
      found_source_root = target_path

    if allowed_types and not isinstance(target, allowed_types):
      raise TargetDefinitionException(target,
                                      'Target type {target_type} not allowed under {source_root}'
                                      .format(target_type=target.type_alias,
                                              source_root=found_source_root))
    return found_source_root

  @classmethod
  def find_by_path(cls, path):
    """Finds a registered source root for a given path

    :param string path: a path containing sources to query
    :returns: the source_root that has been registered as a prefix of the specified path, or None if
    no matching source root was registered.
    """
    if os.path.isabs(path):
      path = SourceRoot._relative_to_buildroot(path)
    found_source_root, _ = cls._SOURCE_ROOT_TREE.get_root_and_types(path)
    return found_source_root

  @classmethod
  def find_siblings_by_path(cls, path):
    """
    :param path: path containing source
    :return: all source root siblings for this path
    """
    if os.path.isabs(path):
      path = SourceRoot._relative_to_buildroot(path)
    return cls._SOURCE_ROOT_TREE.get_root_siblings(path)

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
    cls._register(basedir, False, *allowed_target_types)

  @classmethod
  def register_mutable(cls, basedir, *allowed_target_types):
    """Registers the given basedir (relative to the buildroot) as a source root.

    :param string basedir: The base directory to resolve sources relative to.
    :param list allowed_target_types: Optional list of target types. If specified, we enforce that
      only targets of those types appear under this source root.
    """
    cls._register(basedir, True, *allowed_target_types)

  @classmethod
  def _relative_to_buildroot(cls, path):
    # Verify that source_root_dir doesn't reach outside buildroot.
    buildroot = os.path.normpath(get_buildroot())
    if path.startswith(buildroot):
      abspath = os.path.normpath(path)
    else:
      abspath = os.path.normpath(os.path.join(buildroot, path))
    if not abspath.startswith(buildroot):
      raise ValueError('Source root {} is not under the build root {}'.format(abspath, buildroot))
    return os.path.relpath(abspath, buildroot)

  @classmethod
  def _register(cls, source_root_dir, mutable, *allowed_target_types):
    """Registers a source root.

    :param string source_root_dir: The source root directory against which we resolve source paths,
                     relative to the build root.
    :param list allowed_target_types: Optional list of target types. If specified, we enforce that
                          only targets of those types appear under this source root.
    """
    source_root_dir = SourceRoot._relative_to_buildroot(source_root_dir)

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

    cls._SOURCE_ROOT_TREE.add_root(source_root_dir, allowed_target_types, mutable)

  @classmethod
  def _dump(cls):
    return cls._SOURCE_ROOT_TREE._dump()
