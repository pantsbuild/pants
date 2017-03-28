# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pex.pex_info import PexInfo

from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.tasks.python_task import PythonTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_mkdir_for
from pants.util.fileutil import atomic_copy


class PythonBinaryCreate(PythonTask):
  @classmethod
  def product_types(cls):
    return ['pex_archives', 'deployable_archives']

  @classmethod
  def implementation_version(cls):
    return super(PythonBinaryCreate, cls).implementation_version() + [('PythonBinaryCreate', 1)]

  @property
  def cache_target_dirs(self):
    return True

  @staticmethod
  def is_binary(target):
    return isinstance(target, PythonBinary)

  def __init__(self, *args, **kwargs):
    super(PythonBinaryCreate, self).__init__(*args, **kwargs)
    self._distdir = self.get_options().pants_distdir

  def execute(self):
    binaries = self.context.targets(self.is_binary)

    # Check for duplicate binary names, since we write the pexes to <dist>/<name>.pex.
    names = {}
    for binary in binaries:
      name = binary.name
      if name in names:
        raise TaskError('Cannot build two binaries with the same name in a single invocation. '
                        '{} and {} both have the name {}.'.format(binary, names[name], name))
      names[name] = binary

    with self.invalidated(binaries, invalidate_dependents=True) as invalidation_check:
      python_deployable_archive = self.context.products.get('deployable_archives')
      python_pex_product = self.context.products.get('pex_archives')
      for vt in invalidation_check.all_vts:
        pex_path = os.path.join(vt.results_dir, '{}.pex'.format(vt.target.name))
        if not vt.valid:
          self.context.log.debug('cache for {} is invalid, rebuilding'.format(vt.target))
          self.create_binary(vt.target, vt.results_dir)
        else:
          self.context.log.debug('using cache for {}'.format(vt.target))

        python_pex_product.add(vt.target, os.path.dirname(pex_path)).append(os.path.basename(pex_path))
        python_deployable_archive.add(vt.target, os.path.dirname(pex_path)).append(os.path.basename(pex_path))
        self.context.log.debug('created {}'.format(os.path.relpath(pex_path, get_buildroot())))

        # Create a copy for pex.
        pex_copy = os.path.join(self._distdir, os.path.basename(pex_path))
        safe_mkdir_for(pex_copy)
        atomic_copy(pex_path, pex_copy)
        self.context.log.info('created pex {}'.format(os.path.relpath(pex_copy, get_buildroot())))

  def create_binary(self, binary, results_dir):
    interpreter = self.select_interpreter_for_targets(binary.closure())

    run_info_dict = self.context.run_tracker.run_info.get_as_dict()
    build_properties = PexInfo.make_build_properties()
    build_properties.update(run_info_dict)

    pexinfo = binary.pexinfo.copy()
    pexinfo.build_properties = build_properties

    with self.temporary_chroot(interpreter=interpreter, pex_info=pexinfo, targets=[binary],
                               platforms=binary.platforms) as chroot:
      pex_path = os.path.join(results_dir, '{}.pex'.format(binary.name))
      chroot.package_pex(pex_path)
      return pex_path
