# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload

from pants.contrib.node.targets.npm_package import NpmPackage


class NodeModule(NpmPackage):
  """Represents a Node module."""

  def __init__(self, sources=None, address=None, payload=None, **kwargs):
    """
    :param sources: Javascript and other source code files that make up this module; paths are
                    relative to the BUILD file's directory.
    :type sources: `globs`, `rglobs` or a list of strings
    """
    # TODO(John Sirois): Support devDependencies, etc.  The devDependencies case is not
    # clear-cut since pants controlled builds would provide devDependencies as needed to perform
    # tasks.  The reality is likely to be though that both pants will never cover all cases, and a
    # back door to execute new tools during development will be desirable and supporting conversion
    # of pre-existing package.json files as node_module targets will require this.
    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources=sources,
                                           sources_rel_path=address.spec_path,
                                           key_arg='sources'),
    })
    super(NodeModule, self).__init__(address=address, payload=payload, **kwargs)
