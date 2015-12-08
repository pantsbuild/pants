# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.fs import archive

from pants.contrib.node.tasks.node_paths import NodePaths
from pants.contrib.node.tasks.node_task import NodeTask


class NodeBundle(NodeTask):
  """Create an archive bundle of NodeModule targets."""

  @classmethod
  def register_options(cls, register):
    super(NodeBundle, cls).register_options(register)
    register('--archive', choices=list(archive.TYPE_NAMES),
             default='tgz',
             fingerprint=True,
             help='Create an archive of this type.')
    register('--archive-prefix', action='store_true', default=False,
             fingerprint=True,
             help='If --archive is specified, use the target basename as the path prefix.')

  @classmethod
  def product_types(cls):
    return ['node_bundles']

  def __init__(self, *args, **kwargs):
    super(NodeBundle, self).__init__(*args, **kwargs)
    self._outdir = self.get_options().pants_distdir
    self._prefix = self.get_options().archive_prefix
    self._archiver_type = self.get_options().archive

  def execute(self):
    archiver = archive.archiver(self._archiver_type)
    node_paths = self.context.products.get_data(NodePaths)

    for target in self.context.target_roots:
      if self.is_node_module(target):
        archivepath = archiver.create(
          node_paths.node_path(target),
          self._outdir,
          target.package_name,
          prefix=target.package_name if self._prefix else None
        )
        self.context.log.info('created {}'.format(os.path.relpath(archivepath, get_buildroot())))
