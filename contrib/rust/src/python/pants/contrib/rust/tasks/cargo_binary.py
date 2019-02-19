# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import shutil

from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_mkdir

from pants.contrib.rust.tasks.cargo_task import CargoTask


class Binary(CargoTask):
  @classmethod
  def prepare(cls, options, round_manager):
    super(Binary, cls).prepare(options, round_manager)
    round_manager.require_data('rust_libs')
    round_manager.require_data('rust_bins')

  @classmethod
  def supports_passthru_args(cls):
    return True

  @classmethod
  def implementation_version(cls):
    return super(Binary, cls).implementation_version() + [('Cargo_Binary', 1)]

  def copy_files_into_dist(self, files, bin=False):
    build_root = get_buildroot()
    dist_path = self.get_options().pants_distdir
    path_libs = os.path.join(dist_path, 'lib')
    path_bins = os.path.join(dist_path, 'bin')

    if not os.path.isdir(path_libs):
      safe_mkdir(path_libs)

    if not os.path.isdir(path_bins):
      safe_mkdir(path_bins)

    for name, paths in files.items():
      if bin:
        path_project = os.path.join(path_bins, name)
      else:
        path_project = os.path.join(path_libs, name)
      if not os.path.isdir(path_project):
        safe_mkdir(path_project)

      for path in paths:
        self.context.log.info('Copy: {0}\n\tto: {1}'.format(os.path.relpath(path, build_root),
                                                            os.path.relpath(path_project,
                                                                            build_root)))
        if os.path.isfile(path):
          shutil.copy(path, path_project)
        else:
          dest_path = os.path.join(path_project, os.path.basename(path))
          shutil.rmtree(dest_path, ignore_errors=True)
          shutil.copytree(path, dest_path)

  def execute(self):
    rust_libs = self.context.products.get_data('rust_libs')
    rust_bins = self.context.products.get_data('rust_bins')

    self.copy_files_into_dist(rust_libs)
    self.copy_files_into_dist(rust_bins, bin=True)
