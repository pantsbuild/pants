# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from copy import copy

from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder

from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.tasks2.gather_sources import GatherSources
from pants.backend.python.tasks2.resolve_requirements import ResolveRequirements
from pants.backend.python.tasks2.resolve_requirements_task_base import ResolveRequirementsTaskBase
from pants.build_graph.address import Address


class WrappedPEX(object):
  """Wrapper around a PEX that exposes only its run() method.

  Allows us to set the PEX_PATH in the environment when running.
  """

  def __init__(self, pex, extra_pex_paths, interpreter):
    self._pex = pex
    self._extra_pex_paths = extra_pex_paths
    self._interpreter = interpreter

  @property
  def interpreter(self):
    return self._interpreter

  def run(self, *args, **kwargs):
    kwargs_copy = copy(kwargs)
    env = copy(kwargs_copy.get('env')) if 'env' in kwargs_copy else {}
    env['PEX_PATH'] = self._extra_pex_paths
    kwargs_copy['env'] = env
    return self._pex.run(*args, **kwargs_copy)

  def path(self):
    return self._pex.path()


class PythonExecutionTaskBase(ResolveRequirementsTaskBase):
  """Base class for tasks that execute user Python code in a PEX environment.

  Note: Extends ResolveRequirementsTaskBase because it may need to resolve
  extra requirements in order to execute the code.
  """

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)
    round_manager.require_data(ResolveRequirements.REQUIREMENTS_PEX)
    round_manager.require_data(GatherSources.PYTHON_SOURCES)

  def extra_requirements(self):
    """Override to provide extra requirements needed for execution.

    Must return a list of pip-style requirement strings.
    """
    return []

  def create_pex(self, path, pex_info):
    """Returns a wrapped pex that "merges" the other pexes via PEX_PATH."""
    interpreter = self.context.products.get_data(PythonInterpreter)
    builder = PEXBuilder(path, interpreter, pex_info=pex_info)
    builder.freeze()

    pexes = [
      self.context.products.get_data(ResolveRequirements.REQUIREMENTS_PEX),
      self.context.products.get_data(GatherSources.PYTHON_SOURCES)
    ]

    if self.extra_requirements():
      extra_reqs = [PythonRequirement(req_str) for req_str in self.extra_requirements()]
      addr = Address.parse('{}_extra_reqs'.format(self.__class__.__name__))
      self.context.build_graph.inject_synthetic_target(
        addr, PythonRequirementLibrary, requirements=extra_reqs)
      # Add the extra requirements first, so they take precedence over any colliding version
      # in the target set's dependency closure.
      pexes = [self.resolve_requirements([self.context.build_graph.get_target(addr)])] + pexes

    extra_pex_paths = os.pathsep.join([pex.path() for pex in pexes])
    return WrappedPEX(PEX(path, interpreter), extra_pex_paths, interpreter)
