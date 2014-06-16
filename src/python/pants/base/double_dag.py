# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.abbreviate_target_ids import abbreviate_target_ids


# This file contains the implementation for a doubly-linked DAG data structure that is useful for dependency analysis.

class DoubleDagNode(object):
  def __init__(self, data):
    self.data = data
    self.parents = set()
    self.children = set()

  def __repr__(self):
    return "Node(%s)" % self.data.id


class DoubleDag(object):
  """This implementation of a doubly-linked DAG builds itself from a list of objects (of theoretically unknown type)
  and a function for generating each object's "children". It wraps each object in a "node" structure and exposes the
  following:

    - list of all nodes in the DAG (.nodes)
    - lookup dag node from original object (.lookup)
    - set of leaf nodes (.leaves)
    - a method (remove_nodes) that removes nodes and updates the set of leaves appropriately
    - the inverse method (restore_nodes)

  These are useful for computing the order in which to compile what groups of targets.
  """
  def __init__(self, objects, child_fn, logger):
    self._child_fn = child_fn
    self._logger = logger

    self.nodes = [ DoubleDagNode(object) for object in objects ]

    node_ids = [ node.data.id for node in self.nodes ]
    abbreviated_id_map = abbreviate_target_ids(node_ids)
    for node in self.nodes:
      node.short_id = abbreviated_id_map[node.data.id]
      node.data.short_id = abbreviated_id_map[node.data.id]

    self._nodes_by_data_map = {}
    for node in self.nodes:
      self._nodes_by_data_map[node.data] = node

    self._roots = set([])
    self.leaves = set([])

    self._logger.debug("%d nodes:" % len(self.nodes))
    for node in self.nodes:
      self._logger.debug(node.data.id,)
    self._logger.debug('')

    self._init_parent_and_child_relationships()

    self._find_roots_and_leaves()

    self._logger.debug("%d roots:" % len(self._roots))
    for root in self._roots:
      self._logger.debug(root.data.id)
    self._logger.debug('')

    self._logger.debug("%d leaves:" % len(self.leaves))
    for leaf in self.leaves:
      self._logger.debug(leaf.data.id)
    self._logger.debug('')


  def print_tree(self, use_short_ids=True):
    """This method prints out a python dictionary representing this DAG in a format suitable for eval'ing and useful
    for debugging."""
    def short_id(node):
      return node.short_id
    def id(node):
      return node.data.id

    node_fn = short_id if use_short_ids else id
    self._logger.debug("deps = {")
    for node in self.nodes:
      self._logger.debug(
        """  "%s": {"num": %d, "children": [%s]},""" % (
          node_fn(node),
          node.data.num_sources,
          ','.join(['"%s"' % node_fn(child) for child in node.children]))
      )
    self._logger.debug('}')
    self._logger.debug('')

  def lookup(self, data):
    if data in self._nodes_by_data_map:
      return self._nodes_by_data_map[data]
    return None

  def _init_parent_and_child_relationships(self):
    def find_children(original_node, data):
      for child_data in self._child_fn(data):
        if child_data in self._nodes_by_data_map:
          child_node = self._nodes_by_data_map[child_data]
          original_node.children.add(child_node)
          child_node.parents.add(original_node)
        else:
          raise Exception(
            "DAG child_fn shouldn't yield data objects not in tree:\n %s. child of: %s. original data: %s" % (
              str(child_data),
              str(data),
              str(original_node.data)))

    for node in self.nodes:
      find_children(node, node.data)


  def _find_roots_and_leaves(self):
    for node in self.nodes:
      if not node.parents:
        self._roots.add(node)
      if not node.children:
        self.leaves.add(node)


  def remove_nodes(self, nodes):
    """Removes the given nodes, updates self.leaves accordingly, and returns any nodes that have become leaves as a
    result of this removal."""
    new_leaves = set()
    for node in nodes:
      if node not in self.nodes:
        raise Exception("Attempting to remove invalid node: %s" % node.data.id)
      for parent_node in node.parents:
        if parent_node in nodes:
          continue
        parent_node.children.remove(node)
        if not parent_node.children:
          new_leaves.add(parent_node)

    # Do these outside in case 'nodes' is in fact self.leaves, so that we don't change the set we're iterating over.
    self.leaves -= nodes
    self.leaves.update(new_leaves)
    return new_leaves
