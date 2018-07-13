# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.base.workunit import WorkUnitLabel

from pants.contrib.cpp.tasks.cpp_task import CppTask


class CppBinaryCreate(CppTask):
  """Builds an executable file from C++ sources and libraries."""

  @classmethod
  def register_options(cls, register):
    super(CppBinaryCreate, cls).register_options(register)
    register('--ld-options', help='Append these options to the link command line.')

  @classmethod
  def product_types(cls):
    return ['exe', 'deployable_archives']

  @classmethod
  def prepare(cls, options, round_manager):
    super(CppBinaryCreate, cls).prepare(options, round_manager)
    round_manager.require('lib')
    round_manager.require('objs')

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    with self.context.new_workunit(name='cpp-binary', labels=[WorkUnitLabel.TASK]):
      targets = self.context.targets(self.is_binary)
      with self.invalidated(targets, invalidate_dependents=True) as invalidation_check:
        binary_mapping = self.context.products.get('exe')
        deployable_archives_mapping = self.context.products.get('deployable_archives')
        for vt in invalidation_check.all_vts:
          binary_path = os.path.join(vt.results_dir, vt.target.name)
          if not vt.valid:
            self._create_binary(vt.target, binary_path)
          binary_mapping.add(vt.target, vt.results_dir).append(binary_path)
          deployable_archives_mapping.add(vt.target,  os.path.dirname(binary_path)).append(os.path.basename(binary_path))

  def _create_binary(self, target, binary_path):
    objects = []
    for basedir, objs in self.context.products.get('objs').get(target).items():
      objects.extend([os.path.join(basedir, obj) for obj in objs])
    self._link_binary(target, binary_path, objects)
    self.context.log.info('Built c++ binary: {0}'.format(binary_path))

  def _libname(self, libpath):
    """Converts a full library filepath to the library's name.
    Ex: /path/to/libhello.a --> hello
    """
    # Cut off 'lib' at the beginning of filename, and '.a' at end.
    return os.path.basename(libpath)[3:-2]

  def _link_binary(self, target, binary_path, objects):
    cmd = [self.cpp_toolchain.compiler]

    library_dirs = []
    libraries = []

    # TODO(dhamon): should this use self.context.products.get('lib').get(binary).items()
    def add_library(target):
      product_map = self.context.products.get('lib').get(target)
      if product_map:
        for dir, libs in product_map.items():
          library_dirs.append(dir)
          libraries.extend((self._libname(l) for l in libs))

    target.walk(add_library)

    if target.libraries:
      libraries.extend(target.libraries)

    cmd.extend(objects)
    cmd.extend(('-L{0}'.format(L) for L in library_dirs))
    cmd.extend(('-l{0}'.format(l) for l in libraries))
    cmd.extend(['-o' + binary_path])
    if self.get_options().ld_options != None:
      cmd.extend(('-Wl,{0}'.format(o) for o in self.get_options().ld_options.split(' ')))

    with self.context.new_workunit(name='cpp-link', labels=[WorkUnitLabel.COMPILER]) as workunit:
      self.run_command(cmd, workunit)
