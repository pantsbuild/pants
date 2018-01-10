# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.util.dirutil import safe_mkdir

from pants.contrib.codeanalysis.tasks.indexable_java_targets import IndexableJavaTargets


class BundleEntries(NailgunTask):
  @classmethod
  def prepare(cls, options, round_manager):
    super(BundleEntries, cls).prepare(options, round_manager)
    round_manager.require_data('kythe_entries_files')

  @classmethod
  def register_options(cls, register):
    super(BundleEntries, cls).register_options(register)
    register('--archive', type=str,
             choices=['none', 'uncompressed', 'tar', 'zip', 'gztar', 'bztar'],
             default='none', fingerprint=True,
             help='Create an archive of this type.')

  def execute(self):
    archive = self.get_options().archive
    if archive == 'none':
      return

    indexable_targets = IndexableJavaTargets.global_instance().get(self.context)
    for tgt in indexable_targets:
      entries = self.context.products.get_data('kythe_entries_files', dict)[tgt]
      kythe_distdir = os.path.join(self.get_options().pants_distdir, 'kythe')
      safe_mkdir(kythe_distdir)
      uncompressed_kythe_distpath = os.path.join(
        kythe_distdir, '{}.entries'.format(tgt.address.path_safe_spec))
      if archive == 'uncompressed':
        kythe_distpath = uncompressed_kythe_distpath
        shutil.copy(entries, kythe_distpath)
      else:
        kythe_distpath = shutil.make_archive(base_name=uncompressed_kythe_distpath,
                                             format=archive,
                                             root_dir=os.path.dirname(entries),
                                             base_dir=os.path.basename(entries))
      self.context.log.info('Copied entries to {}'.format(kythe_distpath))
