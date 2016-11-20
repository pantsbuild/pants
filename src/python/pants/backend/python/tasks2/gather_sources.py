# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder

from pants.backend.python.targets.python_target import PythonTarget
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.resources import Resources
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.task.task import Task


class GatherSources(Task):
  """Gather local Python sources.

  Creates an (unzipped) PEX on disk containing the local Python sources.
  This PEX can be merged with a requirements PEX to create a unified Python environment
  for running the relevant python code.
  """

  PYTHON_SOURCES = 'python_sources'

  @classmethod
  def product_types(cls):
    return [cls.PYTHON_SOURCES]

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)

  def execute(self):
    targets = self.context.targets(lambda tgt: isinstance(tgt, (PythonTarget, Resources)))
    with self.invalidated(targets) as invalidation_check:
      # If there are no relevant targets, we still go through the motions of gathering
      # an empty set of sources, to prevent downstream tasks from having to check
      # for this special case.
      if invalidation_check.all_vts:
        target_set_id = VersionedTargetSet.from_versioned_targets(
            invalidation_check.all_vts).cache_key.hash
      else:
        target_set_id = 'no_targets'

      path = os.path.join(self.workdir, target_set_id)
      path_tmp = path + '.tmp'

      shutil.rmtree(path_tmp, ignore_errors=True)

      interpreter = self.context.products.get_data(PythonInterpreter)
      if not os.path.isdir(path):
        self._build_pex(interpreter, path_tmp, invalidation_check.all_vts)
        shutil.move(path_tmp, path)

    pex = PEX(os.path.realpath(path), interpreter=interpreter)
    self.context.products.get_data(self.PYTHON_SOURCES, lambda: pex)

  def _build_pex(self, interpreter, path, vts):
    builder = PEXBuilder(path=path, interpreter=interpreter, copy=True)
    for vt in vts:
      self._dump_sources(builder, vt.target)
    builder.freeze()

  def _dump_sources(self, builder, tgt):
    buildroot = get_buildroot()
    self.context.log.debug('  Dumping sources: {}'.format(tgt))
    for relpath in tgt.sources_relative_to_source_root():
      try:
        src = os.path.join(buildroot, tgt.target_base, relpath)
        builder.add_source(src, relpath)
      except OSError:
        self.context.log.error('Failed to copy {} for target {}'.format(
            os.path.join(tgt.target_base, relpath), tgt.address.spec))
        raise

    if getattr(tgt, 'resources', None):
      # No one should be on old-style resources any more.  And if they are,
      # switching to the new python pipeline will be a great opportunity to fix that.
      raise TaskError('Old-style resources not supported for target {}.  '
                      'Depend on resources() targets instead.'.format(tgt.address.spec))
