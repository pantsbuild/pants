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

from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_tests import PythonTests
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
    # We'd like to take all PythonTarget subclasses, but currently PythonThriftLibrary and
    # PythonAntlrLibrary extend PythonTarget, and until we fix that (which we can't do until
    # we remove the old python pipeline entirely) we want to ignore those target types here.
    targets = self.context.targets(lambda tgt: isinstance(tgt, (PythonLibrary, PythonTests, PythonBinary, Resources)))
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

      # Note that we check for the existence of the directory, instead of for invalid_vts, to cover the empty case.
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
      self._dump_sources(builder, vt.target)
    builder.freeze()

  def _dump_sources(self, builder, tgt):
    buildroot = get_buildroot()
    self.context.log.debug('  Dumping sources: {}'.format(tgt))
    for relpath in tgt.sources_relative_to_source_root():
      try:
        src = os.path.join(buildroot, tgt.target_base, relpath)
        if isinstance(tgt, Resources):
          builder.add_resource(src, relpath)
        else:
          builder.add_source(src, relpath)
      except OSError:
        self.context.log.error('Failed to copy {} for target {}'.format(
            os.path.join(tgt.target_base, relpath), tgt.address.spec))
        raise

    if getattr(tgt, '_resource_target_specs', None) or getattr(tgt, '_synthetic_resources_target', None):
      # No one should be on old-style resources any more.  And if they are,
      # switching to the new python pipeline will be a great opportunity to fix that.
      raise TaskError('Old-style resources not supported for target {}.  '
                      'Depend on resources() targets instead.'.format(tgt.address.spec))
