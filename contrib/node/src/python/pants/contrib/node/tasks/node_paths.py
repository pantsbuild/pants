# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


# TODO(John Sirois): UnionProducts? That seems broken though for ranged version constraints,
# which npm has and are widely used in the community.  For now stay dumb simple (and slow) and
# resolve each node_module individually.
class NodePaths(object):
  """Maps NpmPackage targets to their resolved NODE_PATH chroot."""

  def __init__(self):
    self._paths_by_target = {}

  def resolved(self, target, node_path):
    """Identifies the given target as resolved to the given chroot path.

    :param target: The target that was resolved to the `node_path` chroot.
    :type target: :class:`pants.contrib.node.targets.npm_package.NpmPackage`
    :param string node_path: The chroot path the given `target` was resolved to.
    """
    self._paths_by_target[target] = node_path

  def node_path(self, target):
    """Returns the path of the resolved chroot for the given NpmPackage.

    Returns `None` if the target has not been resolved to a chroot.

    :rtype string
    """
    return self._paths_by_target.get(target)

  @property
  def all_node_paths(self):
    """Return all resolved chroots as a list.

    :rtype list string
    """
    return self._paths_by_target.values()
