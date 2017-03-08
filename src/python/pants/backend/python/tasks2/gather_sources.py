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

from pants.backend.python.tasks2.pex_build_util import dump_sources, has_python_sources
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
  def implementation_version(cls):
    return super(GatherSources, cls).implementation_version() + [('GatherSources', 3)]

  @classmethod
  def product_types(cls):
    return [cls.PYTHON_SOURCES]

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)
    round_manager.require_data('python')  # For codegen.

  def execute(self):
    targets = self.context.targets(predicate=has_python_sources)
    with self.invalidated(targets) as invalidation_check:
      # If there are no relevant targets, we still go through the motions of gathering
      # an empty set of sources, to prevent downstream tasks from having to check
      # for this special case.
      if invalidation_check.all_vts:
        target_set_id = VersionedTargetSet.from_versioned_targets(
            invalidation_check.all_vts).cache_key.hash
      else:
        target_set_id = 'no_targets'

      interpreter = self.context.products.get_data(PythonInterpreter)
      path = os.path.join(self.workdir, target_set_id)

      # Note that we check for the existence of the directory, instead of for invalid_vts,
      # to cover the empty case.
      if not os.path.isdir(path):
        path_tmp = path + '.tmp'
        shutil.rmtree(path_tmp, ignore_errors=True)
        self._build_pex(interpreter, path_tmp, invalidation_check.all_vts)
        shutil.move(path_tmp, path)

    pex = PEX(os.path.realpath(path), interpreter=interpreter)
    self.context.products.get_data(self.PYTHON_SOURCES, lambda: pex)

  def _build_pex(self, interpreter, path, vts):
    builder = PEXBuilder(path=path, interpreter=interpreter, copy=True)
    for vt in vts:
      dump_sources(builder, vt.target, self.context.log)
    builder.freeze()
