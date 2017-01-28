# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.tasks2.resolve_requirements_task_base import ResolveRequirementsTaskBase


class ResolveRequirements(ResolveRequirementsTaskBase):
  REQUIREMENTS_PEX = 'python_requirements_pex'

  @classmethod
  def product_types(cls):
    return [cls.REQUIREMENTS_PEX]

  def execute(self):
    req_libs = self.context.targets(lambda tgt: isinstance(tgt, PythonRequirementLibrary))
    pex = self.resolve_requirements(req_libs)
    self.context.products.get_data(self.REQUIREMENTS_PEX, lambda: pex)
