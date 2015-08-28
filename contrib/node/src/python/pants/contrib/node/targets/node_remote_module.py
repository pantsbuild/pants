# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField

from pants.contrib.node.targets.npm_package import NpmPackage


class NodeRemoteModule(NpmPackage):
  """Represents a remote Node module."""

  def __init__(self, version=None, address=None, payload=None, **kwargs):
    """
    :param string version: The version constraint for the remote node module.  Any of the forms
                           accepted by npm including '' or '*' for unconstrained (the default) are
                           acceptable.  See: https://docs.npmjs.com/files/package.json#dependencies
    """
    if 'dependencies' in kwargs:
      raise TargetDefinitionException(address.spec,
                                      'A node_remote_module does not accept dependencies; instead, '
                                      'they are discovered during resolution (via npm install).')
    payload = payload or Payload()
    payload.add_fields({
      'version': PrimitiveField(version or '*'),  # Guard against/allow `None`.
    })
    super(NodeRemoteModule, self).__init__(address=address, payload=payload, **kwargs)

  @property
  def version(self):
    """The version constraint of the remote package.

    :rtype: string
    """
    return self.payload.version
