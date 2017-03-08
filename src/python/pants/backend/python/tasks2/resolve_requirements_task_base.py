# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder

from pants.backend.python.python_setup import PythonRepos, PythonSetup
from pants.backend.python.tasks2.pex_build_util import dump_requirements
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.task.task import Task
from pants.util.dirutil import safe_rmtree


class ResolveRequirementsTaskBase(Task):
  """Base class for tasks that resolve 3rd-party Python requirements.

  Creates an (unzipped) PEX on disk containing all the resolved requirements.
  This PEX can be merged with other PEXes to create a unified Python environment
  for running the relevant python code.
  """

  @classmethod
  def subsystem_dependencies(cls):
    return (super(ResolveRequirementsTaskBase, cls).subsystem_dependencies() +
            (PythonSetup, PythonRepos))

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)

  def resolve_requirements(self, req_libs):
    with self.invalidated(req_libs) as invalidation_check:
      # If there are no relevant targets, we still go through the motions of resolving
      # an empty set of requirements, to prevent downstream tasks from having to check
      # for this special case.
      if invalidation_check.all_vts:
        target_set_id = VersionedTargetSet.from_versioned_targets(
            invalidation_check.all_vts).cache_key.hash
      else:
        target_set_id = 'no_targets'

      interpreter = self.context.products.get_data(PythonInterpreter)
      path = os.path.join(self.workdir, str(interpreter.identity), target_set_id)

      # Note that we check for the existence of the directory, instead of for invalid_vts,
      # to cover the empty case.
      if not os.path.isdir(path):
        path_tmp = path + '.tmp'
        safe_rmtree(path_tmp)
        self._build_pex(interpreter, path_tmp, req_libs)
        safe_rmtree(path)
        shutil.move(path_tmp, path)

    return PEX(os.path.realpath(path), interpreter=interpreter)

  def _build_pex(self, interpreter, path, req_libs):
    builder = PEXBuilder(path=path, interpreter=interpreter, copy=True)
    dump_requirements(builder, interpreter, req_libs, self.context.log)
    builder.freeze()
