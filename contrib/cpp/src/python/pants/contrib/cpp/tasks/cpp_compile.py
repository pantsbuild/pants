# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.base.workunit import WorkUnitLabel
from pants.util.dirutil import safe_mkdir_for

from pants.contrib.cpp.tasks.cpp_task import CppTask


class CppCompile(CppTask):
  """Compile C++ sources into object files."""

  @classmethod
  def register_options(cls, register):
    super(CppCompile, cls).register_options(register)
    register('--cc-options', advanced=True, type=list, default=[], fingerprint=True,
             help='Append these options to the compiler command line.')
    register('--cc-extensions', advanced=True, type=list, fingerprint=True,
             default=['.cc', '.cxx', '.cpp'],
             help=('The list of extensions to consider when determining if a file is a '
                   'C++ source file.'))

  @classmethod
  def product_types(cls):
    return ['objs']

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    """Compile all sources in a given target to object files."""

    def is_cc(source):
      _, ext = os.path.splitext(source)
      return ext in self.get_options().cc_extensions

    targets = self.context.targets(self.is_cpp)

    # Compile source files to objects.
    with self.invalidated(targets, invalidate_dependents=True) as invalidation_check:
      obj_mapping = self.context.products.get('objs')
      for vt in invalidation_check.all_vts:
        for source in vt.target.sources_relative_to_buildroot():
          if is_cc(source):
            if not vt.valid:
              with self.context.new_workunit(name='cpp-compile', labels=[WorkUnitLabel.MULTITOOL]):
                # TODO: Parallelise the compilation.
                # TODO: Only recompile source files that have changed since the
                #       object file was last written. Also use the output from
                #       gcc -M to track dependencies on headers.
                self._compile(vt.target, vt.results_dir, source)
            objpath = self._objpath(vt.target, vt.results_dir, source)
            obj_mapping.add(vt.target, vt.results_dir).append(objpath)

  def _objpath(self, target, results_dir, source):
    abs_source_root = os.path.join(get_buildroot(), target.target_base)
    abs_source = os.path.join(get_buildroot(), source)
    rel_source = os.path.relpath(abs_source, abs_source_root)
    root, _ = os.path.splitext(rel_source)
    obj_name = root + '.o'

    return os.path.join(results_dir, obj_name)

  def _compile(self, target, results_dir, source):
    """Compile given source to an object file."""
    obj = self._objpath(target, results_dir, source)
    safe_mkdir_for(obj)

    abs_source = os.path.join(get_buildroot(), source)

    # TODO: include dir should include dependent work dir when headers are copied there.
    include_dirs = []
    for dep in target.dependencies:
      if self.is_library(dep):
        include_dirs.extend([os.path.join(get_buildroot(), dep.target_base)])

    cmd = [self.cpp_toolchain.compiler]
    cmd.extend(['-c'])
    cmd.extend(('-I{0}'.format(i) for i in include_dirs))
    cmd.extend(['-o' + obj, abs_source])
    cmd.extend(self.get_options().cc_options)

    # TODO: submit_async_work with self.run_command, [(cmd)] as a Work object.
    with self.context.new_workunit(name='cpp-compile', labels=[WorkUnitLabel.COMPILER]) as workunit:
      self.run_command(cmd, workunit)

    self.context.log.info('Built c++ object: {0}'.format(obj))
