# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.workunit import WorkUnit
from pants.util.dirutil import safe_mkdir

from pants.contrib.cpp.tasks.cpp_task import CppTask


class CppBinaryCreate(CppTask):
  """Builds an executable file from C++ sources and libraries."""

  @classmethod
  def register_options(cls, register):
    super(CppBinaryCreate, cls).register_options(register)
    register('--ld-options', help='Append these options to the link command line.')

  @classmethod
  def product_types(cls):
    return ['exe']

  @classmethod
  def prepare(cls, options, round_manager):
    super(CppBinaryCreate, cls).prepare(options, round_manager)
    round_manager.require('lib')
    round_manager.require('objs')

  def execute(self):
    with self.context.new_workunit(name='cpp-binary', labels=[WorkUnit.TASK]):
      targets = self.context.targets(self.is_binary)
      for target in targets:
        target.workdir = self._workdir

      with self.invalidated(targets, invalidate_dependents=True) as invalidation_check:
        invalid_targets = []
        for vt in invalidation_check.invalid_vts:
          invalid_targets.extend(vt.targets)
        for target in invalid_targets:
          binary = self._create_binary(target)
          self.context.products.get('exe').add(target, self.workdir).append(binary)

  def _create_binary(self, binary):
    objects = []
    for basedir, objs in self.context.products.get('objs').get(binary).items():
      objects.extend([os.path.join(basedir, obj) for obj in objs])
    output = self._link_binary(binary, objects)
    self.context.log.info('Built c++ binary: {0}'.format(output))
    return output

  def _link_binary(self, target, objects):
    output = os.path.join(self.workdir, target.id, target.name)
    safe_mkdir(os.path.dirname(output))

    cmd = [self.cpp_toolchain.compiler]

    library_dirs = []
    libraries = []

    # TODO(dhamon): should this use self.context.products.get('lib').get(binary).items()
    def add_library(tgt):
      for dep in tgt.dependencies:
        if self.is_library(dep):
          library_dirs.extend([os.path.join(dep.workdir, dep.id)])
          libraries.extend([dep.name])

    target.walk(add_library)

    if target.libraries != None:
      libraries.extend(target.libraries)

    cmd.extend(objects)
    cmd.extend(('-L{0}'.format(L) for L in library_dirs))
    cmd.extend(('-l{0}'.format(l) for l in libraries))
    cmd.extend(['-o' + output])
    if self.get_options().ld_options != None:
      cmd.extend(('-Wl,{0}'.format(o) for o in self.get_options().ld_options.split(' ')))

    with self.context.new_workunit(name='cpp-link', labels=[WorkUnit.COMPILER]) as workunit:
      self.run_command(cmd, workunit)

    return output
