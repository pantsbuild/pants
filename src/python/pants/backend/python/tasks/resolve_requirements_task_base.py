# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder

from pants.backend.python.tasks2.build_local_python_distributions import BuildLocalPythonDistributions
from pants.backend.python.tasks2.pex_build_util import dump_requirements, targets_are_invalid
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.task.task import Task
from pants.util.dirutil import safe_concurrent_creation


class ResolveRequirementsTaskBase(Task):
  """Base class for tasks that resolve 3rd-party Python requirements.

  Creates an (unzipped) PEX on disk containing all the resolved requirements.
  This PEX can be merged with other PEXes to create a unified Python environment
  for running the relevant python code.
  """

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)
    round_manager.require_data(BuildLocalPythonDistributions.PYTHON_DISTS)

  def resolve_requirements(self, req_libs, python_dist_targets=()):
    """Requirements resolution for PEX files.

    :param req_libs: A list of :class:`PythonRequirementLibrary` targets to resolve.
    :param python_dist_targets: A list of :class:`PythonDistribution` targets to resolve.
    :returns: a PEX containing target requirements and any specified python dist targets.
    """
    tgts = req_libs + python_dist_targets
    with self.invalidated(tgts) as invalidation_check:
      # If there are no relevant targets, we still go through the motions of resolving
      # an empty set of requirements, to prevent downstream tasks from having to check
      # for this special case.
      if invalidation_check.all_vts:
        target_set_id = VersionedTargetSet.from_versioned_targets(
            invalidation_check.all_vts).cache_key.hash
      else:
        target_set_id = 'no_targets'

      interpreter = self.context.products.get_data(PythonInterpreter)
      path = os.path.realpath(os.path.join(self.workdir, str(interpreter.identity), target_set_id))

      # Gather invalid targets so we can check whether the requirements pex should be
      # rebuilt due to changes to PythonDistribution targets.
      invalid_targets = [vt.target for vt in invalidation_check.invalid_vts]
      # Note that we check for the existence of the directory, instead of for invalid_vts,
      # to cover the empty case.
      if not os.path.isdir(path) or targets_are_invalid(python_dist_targets, invalid_targets):
        with safe_concurrent_creation(path) as safe_path:
          self._build_requirements_pex(interpreter, safe_path, req_libs)
    return PEX(path, interpreter=interpreter)

  def _build_requirements_pex(self, interpreter, path, req_libs):
    builder = PEXBuilder(path=path, interpreter=interpreter, copy=True)
    dump_requirements(builder, interpreter, req_libs, self.context.log)
    # Dump built python distributions, if any, into the requirements pex.
    # NB: If a python_dist depends on a requirement X and another target in play requires
    # an incompatible version of X, this will cause the pex resolver to throw an incompatiblity
    # error and Pants will abort the build.
    built_dists = self.context.products.get_data(BuildLocalPythonDistributions.PYTHON_DISTS)
    if built_dists:
      for dist in built_dists:
        builder.add_dist_location(dist)
    builder.freeze()
