# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.base.workunit import WorkUnitLabel

from pants.contrib.cpp.tasks.cpp_task import CppTask


class CppLibraryCreate(CppTask):
  """Builds a static library from C++ sources."""

  @classmethod
  def product_types(cls):
    return ['lib']

  @classmethod
  def prepare(cls, options, round_manager):
    super().prepare(options, round_manager)
    round_manager.require('objs')

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    with self.context.new_workunit(name='cpp-library', labels=[WorkUnitLabel.TASK]):
      targets = self.context.targets(self.is_library)
      with self.invalidated(targets, invalidate_dependents=True) as invalidation_check:
        lib_mapping = self.context.products.get('lib')
        for vt in invalidation_check.all_vts:
          if not vt.valid:
            self._create_library(vt.target, vt.results_dir)
          lib_mapping.add(vt.target, vt.results_dir).append(self._libpath(vt.target, vt.results_dir))

  def _create_library(self, target, results_dir):
    objects = []
    for basedir, objs in self.context.products.get('objs').get(target).items():
      objects = [os.path.join(basedir, obj) for obj in objs]
    # TODO: copy public headers to work dir.
    output = self._link_library(target, results_dir, objects)
    self.context.log.info('Built c++ library: {0}'.format(output))
    return output

  def _libpath(self, target, results_dir):
    return os.path.join(results_dir, 'lib' + target.name + '.a')

  def _link_library(self, target, results_dir, objects):
    output = self._libpath(target, results_dir)

    cmd = [self.cpp_toolchain.register_tool('ar')]
    cmd.extend(['rcs'])
    cmd.extend([output])
    cmd.extend(objects)

    with self.context.new_workunit(name='cpp-link', labels=[WorkUnitLabel.COMPILER]) as workunit:
      self.run_command(cmd, workunit)

    return output
