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
from pants.backend.python.tasks.pex_build_util import is_python_target
from pants.backend.python.tasks.resolve_requirements import ResolveRequirements
from pants.backend.python.tasks.resolve_requirements_task_base import ResolveRequirementsTaskBase
from pants.backend.python.tasks.wrapped_pex import WrappedPEX
from pants.build_graph.files import Files
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.util.contextutil import temporary_file
from pants.util.objects import datatype


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
    round_manager.require_data(GatherSources.PYTHON_SOURCES)

  def extra_requirements(self):
    """Override to provide extra requirements needed for execution.

    :returns: An iterable of pip-style requirement strings.
    :rtype: :class:`collections.Iterable` of str
    """
    return ()

  class ExtraFile(datatype('ExtraFile', ['path', 'content'])):
    """Models an extra file to place in a PEX."""

    @classmethod
    def empty(cls, path):
      """Creates an empty file with the given PEX path.

      :param str path: The path this extra file should have when added to a PEX.
      :rtype: :class:`ExtraFile`
      """
      return cls(path=path, content='')

    def add_to(self, builder):
      """Adds this extra file to a PEX builder.

      :param builder: The PEX builder to add this extra file to.
      :type builder: :class:`pex.pex_builder.PEXBuilder`
      """
      with temporary_file() as fp:
        fp.write(self.content)
        fp.close()
        add = builder.add_source if self.path.endswith('.py') else builder.add_resource
        add(fp.name, self.path)

  def extra_files(self):
    """Override to provide extra files needed for execution.

    :returns: An iterable of extra files to add to the PEX.
    :rtype: :class:`collections.Iterable` of :class:`PythonExecutionTaskBase.ExtraFile`
    """
    return ()

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
        pexes = [
          self.context.products.get_data(ResolveRequirements.REQUIREMENTS_PEX),
          self.context.products.get_data(GatherSources.PYTHON_SOURCES)
        ]

        if self.extra_requirements():
          extra_requirements_pex = self.resolve_requirement_strings(
            interpreter, self.extra_requirements())
          # Add the extra requirements first, so they take precedence over any colliding version
          # in the target set's dependency closure.
          pexes = [extra_requirements_pex] + pexes
        constraints = {constraint for rt in relevant_targets if is_python_target(rt)
                       for constraint in rt.compatibility}

        with self.merged_pex(path, pex_info, interpreter, pexes, constraints) as builder:
          for extra_file in self.extra_files():
            extra_file.add_to(builder)
          builder.freeze()

    return WrappedPEX(PEX(path, interpreter), interpreter)
