# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import shutil

from pants.binaries.binary_util import BinaryUtil
from pants.fs.archive import TGZ
from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import safe_mkdir, safe_open, safe_rmtree
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


logger = logging.getLogger(__name__)


class NodeBinary(object):
  """Encapsulates access to pre-built thrift static binaries."""


  class NodeInstallError(Exception):
    """Indicates a NpmModule download has failed."""


  class NodeFactory(Subsystem):
    options_scope = 'node-binary'

    @classmethod
    def dependencies(cls):
      return (BinaryUtil.Factory,)

    @classmethod
    def register_options(cls, register):
      register('--supportdir', recursive=True, advanced=True, default='bin/node',
               help='Find node binaries under this dir. Used as part of the path to lookup the'
                    'tool with --binary-util-baseurls and --pants-bootstrapdir')
      register('--version', recursive=True, advanced=True, default='0.12.7',
               help='Node binary version. Used as part of the path to lookup the'
                    'tool with --binary-util-baseurls and --pants-bootstrapdir')
      register('--node-root', default=os.path.join(register.bootstrap.pants_bootstrapdir,
                                                   'node'),
               advanced=True, help='Directory where node gets installed')

    @property
    def node_root(self):
      return self.get_options().node_root

    def create(self):
      binary_util = BinaryUtil.Factory.create()
      options = self.get_options()
      return NodeBinary(binary_util, options.supportdir, options.version, options.node_root)

  def __init__(self, binary_util, relpath, version, node_root):
    self._binary_util = binary_util
    self._relpath = relpath
    self._version = version
    self._node_root = node_root

  @property
  def version(self):
    """Returns the version of the node binary.

    :returns string version: The thrift version number string.
    """
    return self._version

  @property
  def node_root(self):
    """Returns the node_root where node binary is unzipped

    :returns string node_root: The path where node binary is unzipped.
    """
    return self._node_root

  @memoized_property
  def path(self):
    """Selects a node binary tarball matching the current os and architecture.

    :returns: The absolute path to a locally cached node binary tarball.
    """
    try:
      node_path = self._binary_util.select_binary(self._relpath, self.version,
                                                  'node-v{0}.tar.gz'.format(self.version),
                                                  write_mode='w')
      with temporary_dir(cleanup=False) as staging_dir:
        stage_root = os.path.join(staging_dir, 'stage')
        TGZ.extract(node_path, stage_root, 'r:gz')
        safe_rmtree(self.node_root)
        logger.debug('Moving {0} to root {0}'.format(node_path, self.node_root))
        shutil.move(stage_root, self.node_root)
    except IOError as e:
      raise NodeBinary.NodeInstallError('Failed to install fetch node due to {0}'.format(e))
    return os.path.join(self.node_root, 'bin')