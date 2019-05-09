# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import str

from future.utils import binary_type, text_type
from pex.interpreter import PythonInterpreter
from pex.pex import PEX

from pants.backend.python.subsystems.pex_build_util import is_python_target
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.tasks.gather_sources import GatherSources
from pants.backend.python.tasks.resolve_requirements import ResolveRequirements
from pants.backend.python.tasks.resolve_requirements_task_base import ResolveRequirementsTaskBase
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

  class ExtraFile(datatype([('path', text_type), ('content', binary_type)])):
    """Models an extra file to place in a PEX."""

    @classmethod
    def empty(cls, path):
      """Creates an empty file with the given PEX path.

      :param str path: The path this extra file should have when added to a PEX.
      :rtype: :class:`ExtraFile`
      """
      return cls(path=path, content=b'')

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

  @classmethod
  def subsystem_dependencies(cls):
    return super(PythonExecutionTaskBase, cls).subsystem_dependencies() + (PythonSetup,)

  def extra_files(self):
    """Override to provide extra files needed for execution.

    :returns: An iterable of extra files to add to the PEX.
    :rtype: :class:`collections.Iterable` of :class:`PythonExecutionTaskBase.ExtraFile`
    """
    return ()

  # TODO: remove `pin_selected_interpreter` arg and constrain all resulting pexes to a single ==
  # interpreter constraint for the globally selected interpreter! This also requries porting
  # `PythonRun` to set 'PEX_PYTHON_PATH' and 'PEX_PYTHON' when invoking the resulting pex, see
  # https://github.com/pantsbuild/pants/pull/7563.
  def create_pex(self, pex_info=None, pin_selected_interpreter=False):
    """Returns a wrapped pex that "merges" other pexes produced in previous tasks via PEX_PATH.

    The returned pex will have the pexes from the ResolveRequirements and GatherSources tasks mixed
    into it via PEX_PATH. Any 3rdparty requirements declared with self.extra_requirements() will
    also be resolved for the global interpreter, and added to the returned pex via PEX_PATH.

    :param pex_info: An optional PexInfo instance to provide to self.merged_pex().
    :type pex_info: :class:`pex.pex_info.PexInfo`, or None
    :param bool pin_selected_interpreter: If True, the produced pex will have a single ==
                                          interpreter constraint applied to it, for the global
                                          interpreter selected by the SelectInterpreter
    task. Otherwise, all of the interpreter constraints from all python targets will applied.
    :rtype: :class:`pex.pex.PEX`
    """
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

        if pin_selected_interpreter:
          constraints = {str(interpreter.identity.requirement)}
        else:
          constraints = {
            constraint for rt in relevant_targets if is_python_target(rt)
            for constraint in PythonSetup.global_instance().compatibility_or_constraints(rt.compatibility)
          }
          self.context.log.debug('target set {} has constraints: {}'
                                 .format(relevant_targets, constraints))


        with self.merged_pex(path, pex_info, interpreter, pexes, constraints) as builder:
          for extra_file in self.extra_files():
            extra_file.add_to(builder)
          builder.freeze()

    return PEX(path, interpreter)
