# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.fs import archive
from pants.util import dirutil

from pants.contrib.node.tasks.node_paths import NodePaths
from pants.contrib.node.tasks.node_task import NodeTask


class NodeBundle(NodeTask):
  """Create an archive bundle of NodeModule targets."""

  @classmethod
  def register_options(cls, register):
    super(NodeBundle, cls).register_options(register)
    # Some node modules depend on symlink to function.  Thus we can only support archival type
    # that can preserve symlinks.
    register('--archive', choices=list(archive.TYPE_NAMES_PRESERVE_SYMLINKS),
             default='tgz',
             fingerprint=True,
             help='Create an archive of this type.')
    register('--archive-prefix', type=bool, default=False,
             fingerprint=True,
             help='If --archive is specified, use the target basename as the path prefix.')

  @classmethod
  def product_types(cls):
    return ['node_bundles', 'deployable_archives']

  @classmethod
  def prepare(cls, options, round_manager):
    super(NodeBundle, cls).prepare(options, round_manager)
    round_manager.require_data(NodePaths)

  def __init__(self, *args, **kwargs):
    super(NodeBundle, self).__init__(*args, **kwargs)
    self._outdir = self.get_options().pants_distdir
    self._prefix = self.get_options().archive_prefix
    self._archiver_type = self.get_options().archive

  def execute(self):
    archiver = archive.archiver(self._archiver_type)
    node_paths = self.context.products.get_data(NodePaths)

    bundle_archive_product = self.context.products.get('deployable_archives')
    dirutil.safe_mkdir(self._outdir)  # Make sure dist dir is present.

    for target in self.context.target_roots:
      if self.is_node_module(target):
        # build_dir is a symlink.  Since dereference option for tar is set to False, we need to
        # dereference manually to archive the linked build dir.
        build_dir = os.path.realpath(node_paths.node_path(target))
        self.context.log.debug('archiving %s' % build_dir)
        archivepath = archiver.create(
          build_dir,
          self._outdir,
          target.package_name,
          prefix=target.package_name if self._prefix else None,
          dereference=False
        )
        bundle_archive_product.add(
          target, os.path.dirname(archivepath)).append(os.path.basename(archivepath))
        self.context.log.info('created {}'.format(os.path.relpath(archivepath, get_buildroot())))
