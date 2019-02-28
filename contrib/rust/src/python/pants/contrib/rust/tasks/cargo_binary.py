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
  def implementation_version(cls):
    return super(Binary, cls).implementation_version() + [('Cargo_Binary', 1)]

  def copy_libraries_into_dist(self):
    files = self.context.products.get_data('rust_libs')
    dist_path = self.get_options().pants_distdir
    path_libs = os.path.join(dist_path, 'lib')
    safe_mkdir(path_libs, clean=True)
    self.copy_files_into_dist(path_libs, files)

  def copy_binaries_into_dist(self):
    files = self.context.products.get_data('rust_bins')
    dist_path = self.get_options().pants_distdir
    path_bins = os.path.join(dist_path, 'bin')
    safe_mkdir(path_bins, clean=True)
    self.copy_files_into_dist(path_bins, files)

  def copy_files_into_dist(self, libs_bins_path, files):
    build_root = get_buildroot()
    for name, paths in files.items():
      path_project = os.path.join(libs_bins_path, name)
      safe_mkdir(path_project, clean=True)
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
    self.copy_libraries_into_dist()
    self.copy_binaries_into_dist()
