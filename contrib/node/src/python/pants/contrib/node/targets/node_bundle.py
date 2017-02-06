# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.fs import archive as archive_lib

from pants.contrib.node.targets.node_module import NodeModule


class NodeBundle(NodeModule):
  """A bundle of node modules."""

  def __init__(self, node_module=None, archive='tgz', address=None, payload=None, **kwargs):
    """
    :param dependencies: a list of node_modules

    :param archive: a string, select from tar, tgz, tbz2, default to tgz
    """
    if archive not in archive_lib.TYPE_NAMES_PRESERVE_SYMLINKS:
      raise TargetDefinitionException(
        self, '{} is not a valid archive type. Allowed archive types are {}'.format(
          archive,
          ', '.join(sorted(list(archive_lib.TYPE_NAMES_PRESERVE_SYMLINKS)))))

    if not node_module:
      raise TargetDefinitionException(self, 'node_module can not be empty.')

    payload = payload or Payload()
    payload.add_fields({
      'archive': PrimitiveField(archive),
      'node_module': PrimitiveField(node_module),
    })
    super(NodeBundle, self).__init__(address=address, payload=payload, **kwargs)

  @property
  def traversable_dependency_specs(self):
    for spec in super(NodeBundle, self).traversable_dependency_specs:
      yield spec
    if self.payload.node_module:
      yield self.payload.node_module

  @property
  def node_module(self):
    if len(self.dependencies) != 1:
      raise TargetDefinitionException(
        self,
        'A node_bundle must define exactly one node_module dependency, have {}'.format(
          self.dependencies))
    else:
      return self.dependencies[0]
