# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.workunit import WorkUnit
from pants.util.dirutil import safe_mkdir

from pants.contrib.cpp.targets.cpp_library import CppLibrary
from pants.contrib.cpp.tasks.cpp_task import CppTask


class CppLibraryCreate(CppTask):
  """Builds a static library from C++ sources."""

  @classmethod
  def product_types(cls):
    return ['lib']

  def __init__(self, *args, **kwargs):
    super(CppLibraryCreate, self).__init__(*args, **kwargs)

  def execute(self):
    with self.context.new_workunit(name='cpp-library', labels=[WorkUnit.TASK]):
      targets = self.context.targets(self.is_library)
      for target in targets:
        target.workdir = self._workdir

      with self.invalidated(targets, invalidate_dependents=True) as invalidation_check:
        invalid_targets = []
        for vt in invalidation_check.invalid_vts:
          invalid_targets.extend(vt.targets)
        for target in invalid_targets:
          library = self._create_library(target)
          self.context.products.get('lib').add(target, self.workdir).append(library)

  def _create_library(self, library):
    objects = self.compile_sources(library)

    # TODO: copy public headers to work dir.
    output = self._link_library(library, objects)
    self.context.log.info('Built c++ library: {0}'.format(output))
    return output

  def _link_library(self, target, objects):
    def library_name(target):
      return 'lib' + target.name + '.a'

    output_dir = os.path.join(self.workdir, target.id)
    safe_mkdir(output_dir)

    output = os.path.join(output_dir, library_name(target))

    cmd = [self.cpp_toolchain.register_tool('ar')]
    cmd.extend(['rcs'])
    cmd.extend([output])
    cmd.extend(objects)

    with self.context.new_workunit(name='cpp-link', labels=[WorkUnit.COMPILER]):
      self.run_command(cmd)

    return output
