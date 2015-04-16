# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import namedtuple

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot


class Layout(object):

  def __init__(self):
    self._build_root = get_buildroot()
    self.synthetic_lookup = SyntheticTargetLayout()
    self._lookups = [self.synthetic_lookup]

  def add_lookup(self, lookup):
    self._lookups.append(lookup)

  def register(self, path, *types):
    path = self._normalize_path(path)
    self.synthetic_lookup.register(path, False, *types)

  def register_mutable(self, path):
    path = self._normalize_path(path)
    self.synthetic_lookup.register(path, True)

  def _lookup_root(self, path):
    # TODO add trie here
    result = None
    result_lookup = None
    for lookup in self._lookups:
      curr_result = lookup.find_root(path)
      if curr_result and result:
        raise Exception("found root in multiple layouts {}; {} {}".format(result, lookup, result_lookup))
      elif curr_result:
        result = curr_result
        result_lookup = lookup

    return result

  def find_source_root_by_path(self, path):
    path = self._normalize_path(path)
    lookup_result = self._lookup_root(path)
    if lookup_result:
      return lookup_result[0]
    return lookup_result

  def find_source_root_by_path_or_target(self, source, target):
    source = self._normalize_path(source)
    source_root = self.find_source_root_by_path(source)
    if not source_root:
      source_root = self.find_source_root_by_target(target)
    return source_root

  def find_source_root_by_target(self, target):
    lookup_result = self._lookup_root(target.address.spec_path)
    if not lookup_result:
      return target.address.spec_path
    else:
      allowed_types = lookup_result[1]
      if allowed_types and not isinstance(target, tuple(allowed_types)):
        raise Exception("....")
      return lookup_result[0]

  def source_roots(self, target_type):
    # returns list of roots for that type
    result = []
    for lookup_root in self._lookups:
      roots = lookup_root.roots_by_type(target_type)
      # TODO check for overwrites
      result.extend(roots)
    return result

  def all_source_roots(self):
    # returns dict path -> type lists
    result = {}
    for lookup_root in self._lookups:
      roots = lookup_root.all_roots()
      # TODO check for overwrites
      result.update(roots)
    return result

  def find_sibling_source_roots_by_path(self, path):
    path = self._normalize_path(path)
    # only used by idea generation
    #
    # options
    # 1. add a way to get sibling from lookups
    # 2. lookup root for path,
    #    then get child directories for that path
    #    and look up each of those in turn, adding
    #    them to the result
    base_root_result = self._lookup_root(path)
    if not base_root_result:
      return []

    result = []
    path, types = base_root_result
    parent_directory = os.path.sep.join(path.split(os.path.sep)[:-1])
    child_directories = next(os.walk(parent_directory),[None, []])[1]
    for child_directory in child_directories:
      child_lookup = self._lookup_root(child_directory)
      if child_lookup:
        result.append(child_lookup[1])
    return result

  def types(self, path):
    path = self._normalize_path(path)
    result = self._lookup_root(path)
    if result and result[0] == path:
      return result[1]
    else:
      # TODO
      return None

  #def allowed(self, path, type):
  #  pass

  def _normalize_path(self, path):
    #print("path {} buildroot {}".format(path, self._build_root))
    path = path or '.'
    path_relpath = os.path.relpath(path, self._build_root)
    path_normpath = os.path.normpath(path_relpath)
    return path_normpath


# - get all path -> types
# - lookup paths by types

class SourceRootLookup(object):
  #TypeList = namedtuple('TypeList', 'types')
  #AnyType = TypeList(None)

  def all_roots(self):
    # returns dict {path -> types}
    pass

  def roots_by_type(self, type):
    # returns list of roots
    pass

  def find_root(self, sub_path):
    # returns (path, types)
    pass


class SyntheticTargetLayout(SourceRootLookup):
  def __init__(self):
    self.path_to_types = {}
    self.types_to_paths = {}
    self.tree=SourceRootTree()

  def register(self, path, mutable, *types):
    types_for_path = self.path_to_types.get(path)
    if not types_for_path:
      self.path_to_types[path] = OrderedSet(types)
    elif mutable:
      types_for_path.extend(types)
    else:
      raise Exception("path already registered {}".format(path))

    for type in types:
      paths = self.types_to_paths.get(type)
      if paths is None:
        paths = OrderedSet()
        self.types_to_paths[type] = paths
      paths.add(path)

    self.tree.add_root(path, types, mutable)

  def all_roots(self):
    # returns dict {path -> types}
    return dict(self.path_to_types)

  def roots_by_type(self, type):
    # returns list of roots
    return self.types_to_paths.get(type)

  def find_root(self, sub_path):
    # returns (path, types)
    result = self.tree.get_root_and_types(sub_path)
    if result[0]:
      return result
    else:
      return None


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


  def __init__(self):
    self._root = self.Node(key="ROOT")

  def add_root(self, source_root, types, mutable=False):
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
    dir_list = os.path.normpath(path).split(os.path.sep)
    for subdir in dir_list:
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
