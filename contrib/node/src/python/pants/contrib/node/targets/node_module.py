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

  def __init__(
    self, package_manager=None, sources=None, build_script=None, output_dir='dist',
    dev_dependency=False, address=None, payload=None, **kwargs):
    """
    :param sources: Javascript and other source code files that make up this module; paths are
                    relative to the BUILD file's directory.
    :type sources: `globs`, `rglobs` or a list of strings

    :param package_manager: choose among supported package managers (npm or yarn).
    :param build_script: build script name as defined in package.json.  All files that are needed
      for the build script must be included in sources.  The script should output build results
      in the directory specified by output_dir.  If build_script is not supplied, the node
      installation results will be considered as output. The output can be archived or included as
      resources for JVM target.
    :param output_dir: relative path to assets generated by build script. The path will be
      preserved in the created JAR if the target is used as a JVM target dependency.
    :param dev_dependency: boolean value.  Default is False. If a node_module is used as parts
      of devDependencies and thus should not be included in the final bundle or JVM binaries, set
      this value to True.
    """
    # TODO(John Sirois): Support devDependencies, etc.  The devDependencies case is not
    # clear-cut since pants controlled builds would provide devDependencies as needed to perform
    # tasks.  The reality is likely to be though that both pants will never cover all cases, and a
    # back door to execute new tools during development will be desirable and supporting conversion
    # of pre-existing package.json files as node_module targets will require this.
    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(
        sources=sources, sources_rel_path=address.spec_path, key_arg='sources'),
      'build_script': PrimitiveField(build_script),
      'package_manager': PrimitiveField(package_manager),
      'output_dir': PrimitiveField(output_dir),
      'dev_dependency': PrimitiveField(dev_dependency),
    })
    logger.debug('NodeModule payload: %s', payload.fields)
    super(NodeModule, self).__init__(address=address, payload=payload, **kwargs)
