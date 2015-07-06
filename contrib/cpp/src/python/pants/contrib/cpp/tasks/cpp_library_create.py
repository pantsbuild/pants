# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.workunit import WorkUnit
from pants.util.dirutil import safe_mkdir

from pants.contrib.cpp.tasks.cpp_task import CppTask


class CppLibraryCreate(CppTask):
  """Builds a static library from C++ sources."""

  @classmethod
  def product_types(cls):
    return ['lib']

  @classmethod
  def prepare(cls, options, round_manager):
    super(CppLibraryCreate, cls).prepare(options, round_manager)
    round_manager.require('objs')

  def __init__(self, *args, **kwargs):
    super(CppLibraryCreate, self).__init__(*args, **kwargs)

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    with self.context.new_workunit(name='cpp-library', labels=[WorkUnit.TASK]):
      targets = self.context.targets(self.is_library)
      with self.invalidated(targets, invalidate_dependents=True) as invalidation_check:
        for vt in invalidation_check.all_vts:
          self.context.products.get('lib').add(vt.target, vt.results_dir).append(self._libpath(vt))
        for vt in invalidation_check.invalid_vts:
          self._create_library(vt)

  def _create_library(self, vt):
    objects = []
    for basedir, objs in self.context.products.get('objs').get(vt.target).items():
      objects = [os.path.join(basedir, obj) for obj in objs]
    # TODO: copy public headers to work dir.
    output = self._link_library(vt, objects)
    self.context.log.info('Built c++ library: {0}'.format(output))
    return output

  def _libpath(self, vt):
    return os.path.join(vt.results_dir, 'lib' + vt.target.name + '.a')

  def _link_library(self, vt, objects):
    output = self._libpath(vt)

    cmd = [self.cpp_toolchain.register_tool('ar')]
    cmd.extend(['rcs'])
    cmd.extend([output])
    cmd.extend(objects)

    with self.context.new_workunit(name='cpp-link', labels=[WorkUnit.COMPILER]) as workunit:
      self.run_command(cmd, workunit)

    return output
