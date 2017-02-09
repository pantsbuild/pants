# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField

from pants.contrib.node.targets.node_package import NodePackage


logger = logging.getLogger(__name__)


class NodeModule(NodePackage):
  """A Node module."""

  def __init__(self, sources=None, address=None, payload=None, package_manager=None, **kwargs):
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
    package_manager = 'yarnpkg' if package_manager == 'yarn' else package_manager
    if package_manager and package_manager not in ['npm', 'yarnpkg']:
      raise RuntimeError('Unknown package manager: %s' % package_manager)
    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources=sources,
                                           sources_rel_path=address.spec_path,
                                           key_arg='sources'),
      'package_manager': PrimitiveField(str(package_manager)),
    })
    logger.info('NodeModule.__init__ payload:%s ', payload.fields)
    super(NodeModule, self).__init__(address=address, payload=payload, **kwargs)
