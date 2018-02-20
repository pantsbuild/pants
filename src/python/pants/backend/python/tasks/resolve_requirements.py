# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pex.interpreter import PythonInterpreter

from pants.backend.python.tasks.pex_build_util import has_python_requirements
from pants.backend.python.tasks.resolve_requirements_task_base import ResolveRequirementsTaskBase


class ResolveRequirements(ResolveRequirementsTaskBase):
  """Resolve external Python requirements."""
  REQUIREMENTS_PEX = 'python_requirements_pex'

  @classmethod
  def product_types(cls):
    return [cls.REQUIREMENTS_PEX]

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)

  def execute(self):
    interpreter = self.context.products.get_data(PythonInterpreter)
    pex = self.resolve_requirements(interpreter, self.context.targets(has_python_requirements))
    self.context.products.register_data(self.REQUIREMENTS_PEX, pex)
