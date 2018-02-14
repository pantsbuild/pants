# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pex.interpreter import PythonInterpreter
from pex.pex import PEX

from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.tasks.gather_sources import GatherSources
from pants.backend.python.tasks.pex_build_util import has_python_sources
from pants.backend.python.tasks.resolve_requirements import ResolveRequirements
from pants.backend.python.tasks.resolve_requirements_task_base import ResolveRequirementsTaskBase
from pants.backend.python.tasks.wrapped_pex import WrappedPEX
from pants.build_graph.files import Files
from pants.invalidation.cache_manager import VersionedTargetSet


class PythonExecutionTaskBase(ResolveRequirementsTaskBase):
  """Base class for tasks that execute user Python code in a PEX environment.

  Note: Extends ResolveRequirementsTaskBase because it may need to resolve
  extra requirements in order to execute the code.
  """

  @classmethod
  def prepare(cls, options, round_manager):
    super(PythonExecutionTaskBase, cls).prepare(options, round_manager)
    round_manager.require_data(PythonInterpreter)
    round_manager.require_data(ResolveRequirements.REQUIREMENTS_PEX)
    round_manager.require_data(GatherSources.PythonSources)

  def extra_requirements(self):
    """Override to provide extra requirements needed for execution.

    Must return a list of pip-style requirement strings.
    """
    return []

  def create_pex(self, pex_info=None):
    """Returns a wrapped pex that "merges" the other pexes via PEX_PATH."""
    relevant_targets = self.context.targets(
      lambda tgt: isinstance(tgt, (
        PythonDistribution, PythonRequirementLibrary, PythonTarget, Files)))
    with self.invalidated(relevant_targets) as invalidation_check:

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

      # Note that we check for the existence of the directory, instead of for invalid_vts,
      # to cover the empty case.
      if not os.path.isdir(path):
        source_pexes = self.context.products.get_data(GatherSources.PythonSources).all()
        requirements_pex = self.context.products.get_data(ResolveRequirements.REQUIREMENTS_PEX)
        pexes = [requirements_pex] + source_pexes
        if self.extra_requirements():
          extra_requirements_pex = self.resolve_requirement_strings(self.extra_requirements())
          # Add the extra requirements first, so they take precedence over any colliding version
          # in the target set's dependency closure.
          pexes = [extra_requirements_pex] + pexes
        constraints = {constraint for rt in relevant_targets if has_python_sources(rt)
                       for constraint in rt.compatibility}
        self.merge_pexes(path, pex_info, interpreter, pexes, constraints)

    return WrappedPEX(PEX(path, interpreter), interpreter)
