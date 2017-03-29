# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pex.interpreter import PythonInterpreter
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo

from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.tasks2.pex_build_util import (dump_requirements, dump_sources,
                                                        has_python_requirements, has_python_sources,
                                                        has_resources)
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.target_scopes import Scopes
from pants.task.task import Task
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir_for
from pants.util.fileutil import atomic_copy


class PythonBinaryCreate(Task):
  """Create an executable .pex file."""

  @classmethod
  def product_types(cls):
    return ['pex_archives', 'deployable_archives']

  @classmethod
  def implementation_version(cls):
    return super(PythonBinaryCreate, cls).implementation_version() + [('PythonBinaryCreate', 2)]

  @property
  def cache_target_dirs(self):
    return True

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)
    round_manager.require_data('python')  # For codegen.

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
          self._create_binary(vt.target, vt.results_dir)
        else:
          self.context.log.debug('using cache for {}'.format(vt.target))

        basename = os.path.basename(pex_path)
        python_pex_product.add(vt.target, os.path.dirname(pex_path)).append(basename)
        python_deployable_archive.add(vt.target, os.path.dirname(pex_path)).append(basename)
        self.context.log.debug('created {}'.format(os.path.relpath(pex_path, get_buildroot())))

        # Create a copy for pex.
        pex_copy = os.path.join(self._distdir, os.path.basename(pex_path))
        safe_mkdir_for(pex_copy)
        atomic_copy(pex_path, pex_copy)
        self.context.log.info('created pex {}'.format(os.path.relpath(pex_copy, get_buildroot())))

  def _create_binary(self, binary_tgt, results_dir):
    """Create a .pex file for the specified binary target."""
    # Note that we rebuild a chroot from scratch, instead of using the REQUIREMENTS_PEX
    # and PYTHON_SOURCES products, because those products are already-built pexes, and there's
    # no easy way to merge them into a single pex file (for example, they each have a __main__.py,
    # metadata, and so on, which the merging code would have to handle specially).
    interpreter = self.context.products.get_data(PythonInterpreter)
    with temporary_dir() as tmpdir:
      # Create the pex_info for the binary.
      run_info_dict = self.context.run_tracker.run_info.get_as_dict()
      build_properties = PexInfo.make_build_properties()
      build_properties.update(run_info_dict)
      pex_info = binary_tgt.pexinfo.copy()
      pex_info.build_properties = build_properties

      builder = PEXBuilder(path=tmpdir, interpreter=interpreter, pex_info=pex_info, copy=True)

      # Find which targets provide sources and which specify requirements.
      source_tgts = []
      req_tgts = []
      for tgt in binary_tgt.closure(exclude_scopes=Scopes.COMPILE):
        if has_python_sources(tgt) or has_resources(tgt):
          source_tgts.append(tgt)
        elif has_python_requirements(tgt):
          req_tgts.append(tgt)

      # Dump everything into the builder's chroot.
      for tgt in source_tgts:
        dump_sources(builder, tgt, self.context.log)
      dump_requirements(builder, interpreter, req_tgts, self.context.log, binary_tgt.platforms)

      # Build the .pex file.
      pex_path = os.path.join(results_dir, '{}.pex'.format(binary_tgt.name))
      builder.build(pex_path)
      return pex_path
