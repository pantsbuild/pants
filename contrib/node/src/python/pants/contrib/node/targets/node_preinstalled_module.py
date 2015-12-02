# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField

from pants.contrib.node.targets.node_module import NodeModule


class NodePreinstalledModule(NodeModule):
  """A NodeModule which resolves deps by downloading an archived node_modules directory."""

  def __init__(self, dependencies_archive_url=None, sources=None,
               address=None, payload=None, **kwargs):
    """
    :param string url: The location of a tar.gz file containing containing a node_modules directory.
    """
    payload = payload or Payload()
    payload.add_fields({
      'dependencies_archive_url': PrimitiveField(dependencies_archive_url),
    })
    super(NodePreinstalledModule, self).__init__(sources=sources, address=address,
                                                 payload=payload, **kwargs)

  @property
  def dependencies_archive_url(self):
    """Where to download the archive containing the node_modules directory.

    :rtype: string
    """
    return self.payload.dependencies_archive_url
