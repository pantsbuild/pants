# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks2.partition_targets import PartitionTargets
from pants.backend.python.tasks2.pex_build_util import has_python_requirements
from pants.backend.python.tasks2.python_task_mixin import PythonTaskMixin
from pants.backend.python.tasks2.resolve_requirements_task_base import ResolveRequirementsTaskBase
from pants.backend.python.tasks2.select_interpreter import SelectInterpreter
from pants.build_graph.target import Target


class ResolveRequirements(PythonTaskMixin, ResolveRequirementsTaskBase):
  """Resolve external Python requirements."""
  REQUIREMENTS_PEX = 'python_requirements_pex'

  @classmethod
  def prepare(self, options, round_manager):
    round_manager.require_data(PartitionTargets.TARGETS_PARTITION)
    round_manager.require_data(SelectInterpreter.PYTHON_INTERPRETERS)

  @classmethod
  def product_types(cls):
    return [cls.REQUIREMENTS_PEX]

  def execute(self):
    pex = {}
    self.context.products.get_data(self.REQUIREMENTS_PEX, lambda: {})
    for subset in self.target_roots_subsets():
      req_libs = filter(has_python_requirements, Target.closure_for_targets(subset))
      requirements_pex[subset] = self.resolve_requirements(
          req_libs, interpreter=self.interpreter_for_targets(subset))
    self.context.products.register_data(self.REQUIREMENTS_PEX, requirements_pex)
